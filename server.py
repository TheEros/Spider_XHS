"""Spider_XHS 的 FastAPI HTTP 服务。

所有上游调用均为同步 I/O，因此路由使用普通 ``def``，FastAPI 会在线程池中
执行它们，避免阻塞事件循环。Cookie 只从服务端环境变量读取，不允许客户端
在请求中传入，防止凭据意外出现在日志和调用链中。
"""

import base64
import os
from functools import lru_cache
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from loguru import logger
from pydantic import BaseModel, Field

from apis.xhs_creator_apis import XHS_Creator_Apis
from apis.xhs_pc_apis import XHS_Apis
from apis.xhs_pugongying_apis import PuGongYingAPI
from apis.xhs_qianfan_apis import QianFanAPI
from xhs_utils.cookie_util import trans_cookies
from xhs_utils.data_util import handle_note_info
from xhs_utils.xhs_creator import XHSCreatorAuth
from xhs_utils.xhs_pc import XHSPcAuth


app = FastAPI(
    title="Spider_XHS HTTP API",
    description="小红书 PC、创作者中心、蒲公英与千帆接口的统一 HTTP 封装。",
    version="2.0.0",
    contact={"name": "Spider_XHS"},
)


# 文档示例只用于 Swagger/ReDoc 展示，不会参与真实请求处理。
OPENAPI_VALUE_EXAMPLES: dict[str, Any] = {
    "url": "https://www.xiaohongshu.com/explore/64b7f000000000001203abcd",
    "urls": [
        "https://www.xiaohongshu.com/explore/64b7f000000000001203abcd",
        "https://www.xiaohongshu.com/explore/64b7f000000000001203abce",
    ],
    "user_id": "5f123456000000000100abcd",
    "keyword": "露营",
    "query": "上海探店",
    "category": "homefeed_recommend",
    "cursor": "",
    "cursor_score": "",
    "xsec_token": "示例 xsec_token",
    "xsec_source": "pc_user",
    "note_id": "64b7f000000000001203abcd",
    "comment": {"id": "示例评论 ID", "note_id": "示例笔记 ID"},
    "media_type": "image",
    "content_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...",
    "video_id": "示例视频 ID",
    "file_id": "示例文件 ID",
    "title": "周末露营记录",
    "desc": "天气很好，分享这次露营体验。",
    "images_base64": ["data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ..."],
    "video_base64": "data:video/mp4;base64,AAAAIGZ0eXBpc29t...",
    "topics": ["露营", "周末去哪儿"],
    "location": "上海市",
    "content_tag": {"一级分类": "美食"},
    "distribution_category": [{"id": "1", "name": "美食"}],
    "product_name": "示例产品",
    "start_time": "2026-08-20",
    "end_time": "2026-08-31",
    "invite_content": "诚邀您参与本次合作。",
    "contact_info": "example@example.com",
}


def _schema_example(schema: dict[str, Any], schemas: dict[str, Any]) -> Any:
    """从 OpenAPI schema 递归生成一个适合在线文档展示的请求示例。"""
    if "$ref" in schema:
        schema = schemas.get(schema["$ref"].rsplit("/", 1)[-1], {})
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("type") == "object" or "properties" in schema:
        return {
            name: OPENAPI_VALUE_EXAMPLES.get(name, _schema_example(value, schemas))
            for name, value in schema.get("properties", {}).items()
        }
    if schema.get("type") == "array":
        return [_schema_example(schema.get("items", {}), schemas)]
    return {"string": "示例值", "integer": 1, "number": 1.0, "boolean": True}.get(
        schema.get("type"), {}
    )


def custom_openapi() -> dict[str, Any]:
    """为所有接口统一补充请求和成功响应示例。"""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schemas = schema.get("components", {}).get("schemas", {})
    success_example = {
        "success": True,
        "message": "成功",
        "data": {"示例字段": "上游接口返回的数据"},
    }
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            json_body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if json_body and "example" not in json_body and "examples" not in json_body:
                json_body["example"] = _schema_example(json_body.get("schema", {}), schemas)
            response_200 = operation["responses"].get("200")
            if response_200 is not None:
                content = response_200.setdefault("content", {}).setdefault("application/json", {})
                content.setdefault("schema", {"type": "object"})
                content.setdefault("example", success_example)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


class UrlRequest(BaseModel):
    url: str = Field(..., min_length=1, description="完整的小红书 URL")


class UrlsRequest(BaseModel):
    urls: list[str] = Field(..., min_items=1, max_items=100)


class UserIdRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class KeywordRequest(BaseModel):
    keyword: str = Field(..., min_length=1)


class CursorRequest(BaseModel):
    cursor: str = ""


class UserPageRequest(UserIdRequest, CursorRequest):
    xsec_token: str = ""
    xsec_source: str = ""


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    require_num: int = Field(10, ge=1, le=1000)
    sort_type_choice: int = Field(0, ge=0, le=4)
    note_type: int = Field(0, ge=0, le=2)
    note_time: int = Field(0, ge=0, le=3)
    note_range: int = Field(0, ge=0, le=3)
    pos_distance: int = Field(0, ge=0, le=2)
    geo: dict[str, float] | None = None


class SearchPageRequest(SearchRequest):
    page: int = Field(1, ge=1)
    search_id: str | None = None


class SearchUserRequest(BaseModel):
    query: str = Field(..., min_length=1)
    require_num: int = Field(10, ge=1, le=1000)


class HomefeedRequest(BaseModel):
    category: str
    require_num: int = Field(10, ge=1, le=1000)


class HomefeedPageRequest(BaseModel):
    category: str
    cursor_score: str = ""
    refresh_type: int = 1
    note_index: int = 0
    num: int = Field(20, ge=1, le=100)
    need_num: int = Field(10, ge=1, le=100)


class NoteCommentPageRequest(BaseModel):
    note_id: str
    xsec_token: str
    cursor: str = ""


class InnerCommentRequest(BaseModel):
    comment: dict[str, Any]
    xsec_token: str
    cursor: str = ""


class CreatorPageRequest(BaseModel):
    page: int = Field(0, ge=0)
    tab: int = Field(0, ge=0)


class MediaRequest(BaseModel):
    media_type: Literal["image", "video"]
    content_base64: str = Field(..., description="媒体文件的 Base64；可含 data URL 前缀")


class PublishRequest(BaseModel):
    title: str = Field("", max_length=100)
    desc: str = ""
    media_type: Literal["image", "video"] = "image"
    images_base64: list[str] = Field(default_factory=list)
    video_base64: str | None = None
    topics: list[str] = Field(default_factory=list)
    location: str | None = None
    post_time: int | None = Field(None, description="定时发布时间，毫秒时间戳")
    privacy_type: int = Field(1, alias="type")

    class Config:
        allow_population_by_field_name = True


class CategoryPageRequest(BaseModel):
    page: int = Field(1, ge=1)
    content_tag: Any = None


class CategoryUsersRequest(BaseModel):
    num: int = Field(20, ge=1, le=1000)
    content_tag: Any = None


class QianfanPageRequest(BaseModel):
    choice: str = "-1"
    distribution_category: list[dict[str, Any]]
    page: int = Field(1, ge=1)


class QianfanUsersRequest(QianfanPageRequest):
    num: int = Field(20, ge=1, le=1000)


class InviteRequest(UserIdRequest):
    product_name: str
    start_time: str
    end_time: str
    invite_content: str
    contact_info: str


def _env(name: str, fallback: str | None = None) -> str:
    value = os.getenv(name) or (os.getenv(fallback) if fallback else None)
    if not value:
        raise HTTPException(503, f"服务端未配置环境变量 {name}")
    return value


@lru_cache(maxsize=1)
def get_pc_api() -> XHS_Apis:
    logger.info("初始化 PC API")
    return XHS_Apis(XHSPcAuth.from_cookie(_env("COOKIES"))).bootstrap()


@lru_cache(maxsize=1)
def get_creator_api() -> XHS_Creator_Apis:
    logger.info("初始化 Creator API")
    return XHS_Creator_Apis(
        XHSCreatorAuth.from_cookie(_env("CREATOR_COOKIES"))
    ).bootstrap()


@lru_cache(maxsize=1)
def get_pgy_api() -> PuGongYingAPI:
    return PuGongYingAPI()


@lru_cache(maxsize=1)
def get_qianfan_api() -> QianFanAPI:
    return QianFanAPI()


def _cookies(name: str) -> dict[str, str]:
    return trans_cookies(_env(name, "COOKIES"))


def _result(result: tuple[bool, str, Any]) -> dict[str, Any]:
    success, message, data = result
    return {"success": bool(success), "message": str(message), "data": data}


def _raw(data: Any, message: str = "成功") -> dict[str, Any]:
    return {"success": True, "message": message, "data": data}


def _decode_media(value: str) -> bytes:
    try:
        encoded = value.split(",", 1)[1] if value.startswith("data:") else value
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(422, "媒体字段不是有效的 Base64") from exc


@app.get("/", tags=["系统"])
def index():
    return {"name": app.title, "version": app.version, "docs": "/docs", "redoc": "/redoc"}


@app.get("/health", tags=["系统"])
def health():
    return {"success": True, "status": "ok"}


# PC：主页、用户、笔记与搜索
@app.get("/api/pc/homefeed/categories", tags=["PC"])
def pc_categories(): return _result(get_pc_api().get_homefeed_all_channel())


@app.post("/api/pc/homefeed", tags=["PC"])
def pc_homefeed(req: HomefeedPageRequest):
    return _result(get_pc_api().get_homefeed_recommend(req.category, req.cursor_score, req.refresh_type, req.note_index, num=req.num, need_num=req.need_num))


@app.post("/api/pc/homefeed/all", tags=["PC"])
def pc_homefeed_all(req: HomefeedRequest): return _result(get_pc_api().get_homefeed_recommend_by_num(req.category, req.require_num))


@app.get("/api/pc/users/me", tags=["PC"])
def pc_me(): return _result(get_pc_api().get_user_me())


@app.post("/api/pc/users/info", tags=["PC"])
def pc_user(req: UserIdRequest): return _result(get_pc_api().get_user_info(req.user_id))


@app.post("/api/pc/users/notes/page", tags=["PC"])
def pc_user_notes_page(req: UserPageRequest): return _result(get_pc_api().get_user_note_info(req.user_id, req.cursor, req.xsec_token, req.xsec_source))


@app.post("/api/pc/users/notes", tags=["PC"])
def pc_user_notes(req: UrlRequest): return _result(get_pc_api().get_user_all_notes(req.url))


@app.post("/api/pc/users/likes/page", tags=["PC"])
def pc_user_likes_page(req: UserPageRequest): return _result(get_pc_api().get_user_like_note_info(req.user_id, req.cursor, req.xsec_token, req.xsec_source))


@app.post("/api/pc/users/likes", tags=["PC"])
def pc_user_likes(req: UrlRequest): return _result(get_pc_api().get_user_all_like_note_info(req.url))


@app.post("/api/pc/users/collects/page", tags=["PC"])
def pc_user_collects_page(req: UserPageRequest): return _result(get_pc_api().get_user_collect_note_info(req.user_id, req.cursor, req.xsec_token, req.xsec_source))


@app.post("/api/pc/users/collects", tags=["PC"])
def pc_user_collects(req: UrlRequest): return _result(get_pc_api().get_user_all_collect_note_info(req.url))


@app.post("/api/pc/notes/detail", tags=["PC"])
@app.post("/api/note", tags=["兼容接口"], include_in_schema=False)
def pc_note(req: UrlRequest):
    result = _result(get_pc_api().get_note_info(req.url))
    if result["success"]:
        items = ((result["data"] or {}).get("data") or {}).get("items") or []
        if items:
            note = dict(items[0]); note["url"] = req.url
            try: result["data"] = handle_note_info(note)
            except Exception as exc: logger.warning(f"笔记标准化失败: {exc}")
    return result


@app.post("/api/pc/notes/batch", tags=["PC"])
@app.post("/api/notes", tags=["兼容接口"], include_in_schema=False)
def pc_notes(req: UrlsRequest):
    rows = []
    for url in req.urls:
        try: rows.append({"url": url, **pc_note(UrlRequest(url=url))})
        except Exception as exc: rows.append({"url": url, "success": False, "message": str(exc), "data": None})
    return _raw(rows, f"处理完成：{sum(bool(x['success']) for x in rows)}/{len(rows)} 成功")


@app.post("/api/pc/search/suggestions", tags=["PC"])
def pc_suggestions(req: KeywordRequest): return _result(get_pc_api().get_search_keyword(req.keyword))


@app.post("/api/pc/search/notes/page", tags=["PC"])
def pc_search_page(req: SearchPageRequest):
    return _result(get_pc_api().search_note(req.query, req.page, req.sort_type_choice, req.note_type, req.note_time, req.note_range, req.pos_distance, req.geo or "", req.search_id))


@app.post("/api/pc/search/notes", tags=["PC"])
@app.post("/api/search", tags=["兼容接口"], include_in_schema=False)
def pc_search(req: SearchRequest):
    return _result(get_pc_api().search_some_note(req.query, req.require_num, req.sort_type_choice, req.note_type, req.note_time, req.note_range, req.pos_distance, req.geo or ""))


@app.post("/api/pc/search/users/page", tags=["PC"])
def pc_search_users_page(query: str = Body(...), page: int = Body(1, ge=1)): return _result(get_pc_api().search_user(query, page))


@app.post("/api/pc/search/users", tags=["PC"])
def pc_search_users(req: SearchUserRequest): return _result(get_pc_api().search_some_user(req.query, req.require_num))


# PC：评论与消息
@app.post("/api/pc/comments/page", tags=["PC"])
def pc_comments_page(req: NoteCommentPageRequest): return _result(get_pc_api().get_note_out_comment(req.note_id, req.cursor, req.xsec_token))


@app.post("/api/pc/comments/all", tags=["PC"])
def pc_comments_all(req: NoteCommentPageRequest): return _result(get_pc_api().get_note_all_out_comment(req.note_id, req.xsec_token))


@app.post("/api/pc/comments/replies/page", tags=["PC"])
def pc_replies_page(req: InnerCommentRequest): return _result(get_pc_api().get_note_inner_comment(req.comment, req.cursor, req.xsec_token))


@app.post("/api/pc/comments/replies/all", tags=["PC"])
def pc_replies_all(req: InnerCommentRequest): return _result(get_pc_api().get_note_all_inner_comment(req.comment, req.xsec_token))


@app.post("/api/pc/notes/comments", tags=["PC"])
def pc_note_comments(req: UrlRequest): return _result(get_pc_api().get_note_all_comment(req.url))


@app.get("/api/pc/messages/unread", tags=["PC"])
def pc_unread(): return _result(get_pc_api().get_unread_message())


@app.post("/api/pc/messages/mentions/page", tags=["PC"])
def pc_mentions_page(req: CursorRequest): return _result(get_pc_api().get_metions(req.cursor))


@app.get("/api/pc/messages/mentions", tags=["PC"])
def pc_mentions(): return _result(get_pc_api().get_all_metions())


@app.post("/api/pc/messages/likes-collects/page", tags=["PC"])
def pc_likes_page(req: CursorRequest): return _result(get_pc_api().get_likesAndcollects(req.cursor))


@app.get("/api/pc/messages/likes-collects", tags=["PC"])
def pc_likes(): return _result(get_pc_api().get_all_likesAndcollects())


@app.post("/api/pc/messages/connections/page", tags=["PC"])
def pc_connections_page(req: CursorRequest): return _result(get_pc_api().get_new_connections(req.cursor))


@app.get("/api/pc/messages/connections", tags=["PC"])
def pc_connections(): return _result(get_pc_api().get_all_new_connections())


# Creator
@app.get("/api/creator/user", tags=["Creator"])
def creator_user(): return _result(get_creator_api().get_user_info())


@app.post("/api/creator/topics", tags=["Creator"])
def creator_topics(req: KeywordRequest): return _result(get_creator_api().get_topic(req.keyword))


@app.post("/api/creator/locations", tags=["Creator"])
def creator_locations(req: KeywordRequest): return _result(get_creator_api().get_location_info(req.keyword))


@app.post("/api/creator/media/permit", tags=["Creator"])
def creator_permit(media_type: Literal["image", "video"] = Body(..., embed=True)): return _result(get_creator_api().get_file_ids(media_type))


@app.post("/api/creator/media/upload", tags=["Creator"])
def creator_upload(req: MediaRequest): return _result(get_creator_api().upload_media(_decode_media(req.content_base64), req.media_type))


@app.post("/api/creator/media/transcode", tags=["Creator"])
def creator_transcode(video_id: str = Body(..., embed=True)): return _result(get_creator_api().query_transcode(video_id))


@app.post("/api/creator/media/encryption", tags=["Creator"])
def creator_encryption(file_id: str = Body(..., embed=True)): return _result(get_creator_api().encryption(file_id))


@app.post("/api/creator/notes/publish", tags=["Creator"])
def creator_publish(req: PublishRequest):
    note = {"title": req.title, "desc": req.desc, "media_type": req.media_type, "topics": req.topics, "location": req.location, "postTime": req.post_time, "type": req.privacy_type}
    if req.media_type == "image":
        if not req.images_base64: raise HTTPException(422, "图文笔记必须提供 images_base64")
        note["images"] = [_decode_media(x) for x in req.images_base64]
    else:
        if not req.video_base64: raise HTTPException(422, "视频笔记必须提供 video_base64")
        note["video"] = _decode_media(req.video_base64)
    return _result(get_creator_api().post_note(note))


@app.post("/api/creator/notes/page", tags=["Creator"])
def creator_notes_page(req: CreatorPageRequest): return _result(get_creator_api().get_posted_notes_page(req.page, req.tab))


@app.post("/api/creator/notes", tags=["Creator"])
def creator_notes(tab: int = Body(0, ge=0, embed=True)): return _result(get_creator_api().get_all_posted_notes(tab))


# 蒲公英
@app.get("/api/pgy/categories", tags=["蒲公英"])
def pgy_categories(): return _raw(get_pgy_api().get_all_categories(_cookies("PUGONGYING_COOKIES")))


@app.post("/api/pgy/track", tags=["蒲公英"])
def pgy_track(data: dict[str, Any]): return _raw(get_pgy_api().get_track(data, _cookies("PUGONGYING_COOKIES")))


@app.post("/api/pgy/users/page", tags=["蒲公英"])
def pgy_users_page(req: CategoryPageRequest):
    users, total = get_pgy_api().get_user_by_page(req.page, _cookies("PUGONGYING_COOKIES"), req.content_tag)
    return _raw({"list": users, "total": total})


@app.post("/api/pgy/users", tags=["蒲公英"])
def pgy_users(req: CategoryUsersRequest): return _raw(get_pgy_api().get_some_user(req.num, _cookies("PUGONGYING_COOKIES"), req.content_tag))


@app.get("/api/pgy/self", tags=["蒲公英"])
def pgy_self(): return _raw(get_pgy_api().get_self_info(_cookies("PUGONGYING_COOKIES")))


def _pgy_user(method: str, req: UserIdRequest): return _raw(getattr(get_pgy_api(), method)(req.user_id, _cookies("PUGONGYING_COOKIES")))


@app.post("/api/pgy/users/detail", tags=["蒲公英"])
def pgy_detail(req: UserIdRequest): return _pgy_user("get_user_detail", req)


@app.post("/api/pgy/users/fans", tags=["蒲公英"])
def pgy_fans(req: UserIdRequest): return _pgy_user("get_user_fans_detail", req)


@app.post("/api/pgy/users/fans/history", tags=["蒲公英"])
def pgy_fans_history(req: UserIdRequest): return _pgy_user("get_user_fans_history", req)


@app.post("/api/pgy/users/notes", tags=["蒲公英"])
def pgy_notes(req: UserIdRequest): return _pgy_user("get_user_notes_detail", req)


@app.post("/api/pgy/invites", tags=["蒲公英"])
def pgy_invite(req: InviteRequest):
    return _raw(get_pgy_api().send_invite(req.user_id, _cookies("PUGONGYING_COOKIES"), req.product_name, [req.start_time, req.end_time], req.invite_content, req.contact_info))


# 千帆
@app.get("/api/qianfan/categories", tags=["千帆"])
def qf_categories(): return _raw(get_qianfan_api().get_all_categories(_cookies("QIANFAN_COOKIES")))


@app.post("/api/qianfan/users/page", tags=["千帆"])
def qf_users_page(req: QianfanPageRequest):
    users, total = get_qianfan_api().get_user_by_page(req.choice, req.distribution_category, req.page, _cookies("QIANFAN_COOKIES"))
    return _raw({"list": users, "total": total})


@app.post("/api/qianfan/users", tags=["千帆"])
def qf_users(req: QianfanUsersRequest): return _raw(get_qianfan_api().get_some_user(req.choice, req.distribution_category, req.num, _cookies("QIANFAN_COOKIES")))


def _qf_user(method: str, req: UserIdRequest): return _raw(getattr(get_qianfan_api(), method)(req.user_id, _cookies("QIANFAN_COOKIES")))


@app.post("/api/qianfan/users/detail", tags=["千帆"])
def qf_detail(req: UserIdRequest): return _qf_user("get_user_detail", req)


@app.post("/api/qianfan/users/cooperation", tags=["千帆"])
def qf_cooperation(req: UserIdRequest): return _qf_user("get_user_cooperation", req)


@app.post("/api/qianfan/users/shops", tags=["千帆"])
def qf_shops(req: UserIdRequest): return _qf_user("get_user_shop", req)


@app.post("/api/qianfan/users/items", tags=["千帆"])
def qf_items(req: UserIdRequest): return _qf_user("get_user_item", req)


@app.post("/api/qianfan/users/fans", tags=["千帆"])
def qf_fans(req: UserIdRequest): return _qf_user("get_user_fans", req)


@app.exception_handler(Exception)
async def unhandled_exception(_request, exc: Exception):
    # HTTPException 由 FastAPI 自己处理；这里只兜底未预期的上游/签名错误。
    logger.exception(f"HTTP API 调用失败: {exc}")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"success": False, "message": str(exc), "data": None})

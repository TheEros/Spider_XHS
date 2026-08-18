import os

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.data_util import handle_note_info
from xhs_utils.xhs_pc import XHSPcAuth

app = FastAPI(
    title="Spider_XHS HTTP API",
    description="Spider_XHS HTTP API wrapper",
    version="1.0.0",
)


# ============================================================
# Auth
# ============================================================

COOKIES = os.getenv("COOKIES")

if not COOKIES:
    logger.warning("COOKIES environment variable is not set")


_auth: XHSPcAuth | None = None
_api: XHS_Apis | None = None


def get_api() -> XHS_Apis:
    """
    延迟初始化 XHS API。

    不在 server.py import 时调用 bootstrap，
    避免 Node / Cookie / b1 出错导致整个 FastAPI 无法启动。
    """

    global _auth
    global _api

    if _api is not None:
        return _api

    if not COOKIES:
        raise RuntimeError("COOKIES environment variable is required")

    logger.info("Initializing XHS API...")

    _auth = XHSPcAuth.from_cookie(COOKIES)

    _api = XHS_Apis(_auth)

    success, msg, _ = _api.bootstrap()

    if not success:
        _api = None
        raise RuntimeError(f"XHS API bootstrap failed: {msg}")

    logger.info("XHS API initialized successfully")

    return _api


# ============================================================
# Request Models
# ============================================================


class NoteRequest(BaseModel):
    url: str = Field(..., description="小红书笔记 URL")


class NotesRequest(BaseModel):
    urls: list[str] = Field(..., description="小红书笔记 URL 列表")


class UserNotesRequest(BaseModel):
    url: str = Field(..., description="小红书用户主页 URL")


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索关键词")

    require_num: int = Field(
        default=10,
        ge=1,
        le=100,
        description="需要返回的数量",
    )

    sort_type_choice: int = Field(
        default=0,
        ge=0,
        le=4,
        description=("排序方式: 0综合 1最新 2最多点赞 3最多评论 4最多收藏"),
    )

    note_type: int = Field(
        default=0,
        ge=0,
        le=2,
        description="笔记类型: 0不限 1视频 2图文",
    )

    note_time: int = Field(
        default=0,
        ge=0,
        le=3,
        description="时间: 0不限 1一天内 2一周内 3半年内",
    )

    note_range: int = Field(
        default=0,
        ge=0,
        le=3,
        description="范围: 0不限 1已看过 2未看过 3已关注",
    )

    pos_distance: int = Field(
        default=0,
        ge=0,
        le=2,
        description="距离: 0不限 1同城 2附近",
    )

    geo: dict[str, float] | None = Field(
        default=None,
        description='例如 {"latitude": 39.9725, "longitude": 116.4207}',
    )


# ============================================================
# Health
# ============================================================


@app.get("/health")
async def health():
    return {
        "success": True,
        "status": "ok",
    }


# ============================================================
# Single Note
# ============================================================


@app.post("/api/note")
async def get_note(req: NoteRequest):
    """
    获取单篇笔记。
    """

    try:
        api = get_api()

        success, msg, note_info = api.get_note_info(req.url)

        if not success:
            return {
                "success": False,
                "message": msg,
                "data": None,
            }

        if note_info and "data" in note_info:
            items = note_info["data"].get("items", [])

            if items:
                note_info = items[0]

                note_info["url"] = req.url

                try:
                    note_info = handle_note_info(note_info)
                except Exception as e:
                    logger.warning(f"handle_note_info failed: {e}")

        return {
            "success": True,
            "message": msg,
            "data": note_info,
        }

    except Exception as e:
        logger.exception("get note failed")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# Batch Notes
# ============================================================


@app.post("/api/notes")
async def get_notes(req: NotesRequest):
    """
    批量获取笔记。

    注意：
    这里 HTTP API 只返回数据，
    不执行原项目的媒体下载 / Excel 保存。
    """

    api = get_api()

    results = []

    for url in req.urls:
        try:
            success, msg, note_info = api.get_note_info(url)

            if success:
                try:
                    items = note_info["data"]["items"]

                    if items:
                        note = items[0]
                        note["url"] = url

                        try:
                            note = handle_note_info(note)
                        except Exception:
                            pass

                        results.append(
                            {
                                "success": True,
                                "url": url,
                                "data": note,
                            }
                        )

                        continue

                except Exception as e:
                    msg = str(e)

            results.append(
                {
                    "success": False,
                    "url": url,
                    "message": str(msg),
                    "data": None,
                }
            )

        except Exception as e:
            logger.exception(f"get note failed: {url}")

            results.append(
                {
                    "success": False,
                    "url": url,
                    "message": str(e),
                    "data": None,
                }
            )

    return {
        "success": True,
        "count": len(results),
        "data": results,
    }


# ============================================================
# User All Notes
# ============================================================


@app.post("/api/user/notes")
async def get_user_notes(req: UserNotesRequest):
    """
    获取指定用户的全部笔记 URL。
    """

    try:
        api = get_api()

        success, msg, notes = api.get_user_all_notes(req.url)

        if not success:
            return {
                "success": False,
                "message": msg,
                "data": [],
            }

        result = []

        for note in notes:
            try:
                note_id = note["note_id"]
                xsec_token = note["xsec_token"]

                note_url = (
                    f"https://www.xiaohongshu.com/explore/"
                    f"{note_id}"
                    f"?xsec_token={xsec_token}"
                )

                result.append(
                    {
                        "note_id": note_id,
                        "xsec_token": xsec_token,
                        "url": note_url,
                        "data": note,
                    }
                )

            except Exception as e:
                logger.warning(f"build note url failed: {e}")

        return {
            "success": True,
            "message": msg,
            "count": len(result),
            "data": result,
        }

    except Exception as e:
        logger.exception("get user notes failed")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# Search
# ============================================================


@app.post("/api/search")
async def search(req: SearchRequest):
    """
    搜索小红书笔记。
    """

    try:
        api = get_api()

        success, msg, notes = api.search_some_note(
            req.query,
            req.require_num,
            req.sort_type_choice,
            req.note_type,
            req.note_time,
            req.note_range,
            req.pos_distance,
            req.geo,
        )

        if not success:
            return {
                "success": False,
                "message": msg,
                "data": [],
            }

        result = []

        for note in notes:
            if note.get("model_type") != "note":
                continue

            try:
                note_id = note["id"]
                xsec_token = note["xsec_token"]

                note_url = (
                    f"https://www.xiaohongshu.com/explore/"
                    f"{note_id}"
                    f"?xsec_token={xsec_token}"
                )

                result.append(
                    {
                        "id": note_id,
                        "xsec_token": xsec_token,
                        "url": note_url,
                        "data": note,
                    }
                )

            except Exception as e:
                logger.warning(f"build search note failed: {e}")

        return {
            "success": True,
            "message": msg,
            "query": req.query,
            "count": len(result),
            "data": result,
        }

    except Exception as e:
        logger.exception("search failed")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

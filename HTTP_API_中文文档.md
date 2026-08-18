# Spider_XHS HTTP API 中文文档

本文档对应 `server.py` 2.0.0。服务同时提供自动生成的 Swagger 文档 `/docs`、ReDoc `/redoc` 和 OpenAPI 描述 `/openapi.json`。

> 本项目仅供学习交流。调用者应遵守小红书平台规则、保护账号凭据和个人信息，并控制请求频率。

## 1. 启动

### 本地启动

```bash
pip install -r requirements-api.txt
npm install
export COOKIES='PC 端完整 Cookie'
export CREATOR_COOKIES='创作者中心完整 Cookie'
export PUGONGYING_COOKIES='蒲公英完整 Cookie'
export QIANFAN_COOKIES='千帆完整 Cookie'
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

也可将变量写入 `.env` 后运行：

```bash
docker compose up --build -d
```

环境变量说明：

| 变量 | 用途 | 是否必需 |
|---|---|---|
| `COOKIES` | 小红书 PC 网页端 | 调用 `/api/pc/*` 时必需 |
| `CREATOR_COOKIES` | 创作者中心 | 调用 `/api/creator/*` 时必需 |
| `PUGONGYING_COOKIES` | 蒲公英；未设置时回退到 `COOKIES` | 调用 `/api/pgy/*` 时必需 |
| `QIANFAN_COOKIES` | 千帆；未设置时回退到 `COOKIES` | 调用 `/api/qianfan/*` 时必需 |

Cookie 只保存在服务端，任何接口都不接收客户端传入的 Cookie。修改环境变量后需重启服务，因为 PC 与 Creator 客户端会在首次调用时初始化并缓存。

## 2. 通用约定

- 基础地址：`http://localhost:8000`
- 除标为 GET 的接口外，均使用 `POST` 和 `Content-Type: application/json`。
- 成功到达上游并不代表上游业务成功，请始终检查响应中的 `success`。
- 参数校验失败返回 HTTP `422`；缺少服务端 Cookie 返回 `503`；未捕获的签名、网络或上游异常返回 `500`。
- 列表页接口只取一页；无 `/page` 后缀的对应接口通常会自动翻页直到达到数量或取完。

统一响应通常为：

```json
{
  "success": true,
  "message": "成功",
  "data": {}
}
```

`data` 保留小红书上游数据结构，可能随平台调整而变化。

## 3. 系统接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务版本及文档入口 |
| GET | `/health` | 存活检查；不验证 Cookie 和上游状态 |

## 4. PC 网页端接口

### 4.1 主页和用户

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| GET | `/api/pc/homefeed/categories` | 无 | 首页全部频道 |
| POST | `/api/pc/homefeed` | `category,cursor_score,refresh_type,note_index,num,need_num` | 推荐流单页 |
| POST | `/api/pc/homefeed/all` | `category,require_num` | 获取指定数量推荐笔记 |
| GET | `/api/pc/users/me` | 无 | 当前账号信息 |
| POST | `/api/pc/users/info` | `user_id` | 用户主页信息 |
| POST | `/api/pc/users/notes/page` | `user_id,cursor,xsec_token,xsec_source` | 用户发布笔记单页 |
| POST | `/api/pc/users/notes` | `url` | 用户全部发布笔记 |
| POST | `/api/pc/users/likes/page` | 同上 | 用户点赞笔记单页 |
| POST | `/api/pc/users/likes` | `url` | 用户全部点赞笔记 |
| POST | `/api/pc/users/collects/page` | 同上 | 用户收藏笔记单页 |
| POST | `/api/pc/users/collects` | `url` | 用户全部收藏笔记 |

用户主页 URL 示例：

```json
{"url":"https://www.xiaohongshu.com/user/profile/用户ID?xsec_token=...&xsec_source=pc_search"}
```

### 4.2 笔记和搜索

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| POST | `/api/pc/notes/detail` | `url` | 笔记详情，并尽量标准化无水印媒体字段 |
| POST | `/api/pc/notes/batch` | `urls`（1～100 个） | 批量详情；单条失败不影响其他项 |
| POST | `/api/pc/search/suggestions` | `keyword` | 搜索联想词 |
| POST | `/api/pc/search/notes/page` | 搜索参数加 `page,search_id` | 搜索笔记单页 |
| POST | `/api/pc/search/notes` | 搜索参数 | 搜索指定数量笔记 |
| POST | `/api/pc/search/users/page` | `query,page` | 搜索用户单页 |
| POST | `/api/pc/search/users` | `query,require_num` | 搜索指定数量用户 |

搜索请求示例：

```json
{
  "query": "露营",
  "require_num": 20,
  "sort_type_choice": 1,
  "note_type": 0,
  "note_time": 2,
  "note_range": 0,
  "pos_distance": 0,
  "geo": null
}
```

枚举含义：

- `sort_type_choice`：`0` 综合、`1` 最新、`2` 最多点赞、`3` 最多评论、`4` 最多收藏。
- `note_type`：`0` 不限、`1` 视频、`2` 图文。
- `note_time`：`0` 不限、`1` 一天内、`2` 一周内、`3` 半年内。
- `note_range`：`0` 不限、`1` 已看过、`2` 未看过、`3` 已关注。
- `pos_distance`：`0` 不限、`1` 同城、`2` 附近。使用位置筛选时 `geo` 传 `{"latitude":39.9,"longitude":116.4}`。

### 4.3 评论和消息

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| POST | `/api/pc/comments/page` | `note_id,xsec_token,cursor` | 一级评论单页 |
| POST | `/api/pc/comments/all` | `note_id,xsec_token` | 全部一级评论 |
| POST | `/api/pc/comments/replies/page` | `comment,xsec_token,cursor` | 某条评论的回复单页；`comment` 为上游评论对象 |
| POST | `/api/pc/comments/replies/all` | `comment,xsec_token` | 某条评论的全部回复 |
| POST | `/api/pc/notes/comments` | `url` | 按完整笔记 URL 获取全部评论及回复 |
| GET | `/api/pc/messages/unread` | 无 | 未读消息汇总 |
| POST | `/api/pc/messages/mentions/page` | `cursor` | 评论和 @ 单页 |
| GET | `/api/pc/messages/mentions` | 无 | 全部评论和 @ |
| POST | `/api/pc/messages/likes-collects/page` | `cursor` | 点赞收藏通知单页 |
| GET | `/api/pc/messages/likes-collects` | 无 | 全部点赞收藏通知 |
| POST | `/api/pc/messages/connections/page` | `cursor` | 新增关注单页 |
| GET | `/api/pc/messages/connections` | 无 | 全部新增关注 |

## 5. 创作者中心接口

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| GET | `/api/creator/user` | 无 | 当前创作者信息 |
| POST | `/api/creator/topics` | `keyword` | 搜索话题 |
| POST | `/api/creator/locations` | `keyword` | 搜索地点 |
| POST | `/api/creator/media/permit` | `media_type` | 获取上传许可 |
| POST | `/api/creator/media/upload` | `media_type,content_base64` | 上传单个图片或视频 |
| POST | `/api/creator/media/transcode` | `video_id` | 查询视频转码 |
| POST | `/api/creator/media/encryption` | `file_id` | 获取图片加密信息 |
| POST | `/api/creator/notes/publish` | 见下文 | 上传媒体并发布笔记 |
| POST | `/api/creator/notes/page` | `page,tab` | 已发布作品单页；起始 `page=0` |
| POST | `/api/creator/notes` | `tab` | 自动翻页获取全部已发布作品 |

发布图文笔记：

```json
{
  "title": "标题",
  "desc": "正文",
  "media_type": "image",
  "images_base64": ["iVBORw0KGgo..."],
  "topics": ["露营", "周末去哪儿"],
  "location": "北京市朝阳公园",
  "post_time": null,
  "type": 1
}
```

发布视频时使用 `"media_type":"video"` 和 `"video_base64":"AAAA..."`，不传 `images_base64`。Base64 既可为纯字符串，也可为 `data:image/png;base64,...` 格式。大文件 Base64 会额外占用约三分之一内存，部署时应同步调整反向代理的请求体限制。`type` 是项目上游发布参数的可见性值，默认 `1`；`post_time` 是毫秒时间戳。

## 6. 蒲公英接口

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| GET | `/api/pgy/categories` | 无 | 全部内容类目 |
| POST | `/api/pgy/track` | 任意完整 track 数据对象 | 创建检索 track |
| POST | `/api/pgy/users/page` | `page,content_tag` | KOL 单页，返回 `list,total` |
| POST | `/api/pgy/users` | `num,content_tag` | 指定数量 KOL |
| GET | `/api/pgy/self` | 无 | 当前品牌方信息 |
| POST | `/api/pgy/users/detail` | `user_id` | KOL 数据总览 |
| POST | `/api/pgy/users/fans` | `user_id` | 粉丝画像 |
| POST | `/api/pgy/users/fans/history` | `user_id` | 粉丝历史趋势 |
| POST | `/api/pgy/users/notes` | `user_id` | 笔记表现数据 |
| POST | `/api/pgy/invites` | 见下例 | 发起合作邀请（会产生外部业务操作） |

```json
{
  "user_id": "博主ID",
  "product_name": "产品名称",
  "start_time": "2026-09-01",
  "end_time": "2026-09-15",
  "invite_content": "邀请说明",
  "contact_info": "联系方式"
}
```

`content_tag` 可直接使用 `/api/pgy/categories` 返回类目组装后的对象；不筛选时传 `null`。

## 7. 千帆接口

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| GET | `/api/qianfan/categories` | 无 | 全部分销类目 |
| POST | `/api/qianfan/users/page` | `choice,distribution_category,page` | 分销商单页 |
| POST | `/api/qianfan/users` | 上述字段加 `num` | 指定数量分销商 |
| POST | `/api/qianfan/users/detail` | `user_id` | 分销商总览 |
| POST | `/api/qianfan/users/cooperation` | `user_id` | 合作品类 |
| POST | `/api/qianfan/users/shops` | `user_id` | 合作店铺 |
| POST | `/api/qianfan/users/items` | `user_id` | 合作商品 |
| POST | `/api/qianfan/users/fans` | `user_id` | 粉丝数据 |

`distribution_category` 原样传入 `/api/qianfan/categories` 返回的数据；`choice` 沿用原脚本语法：`-1` 表示全部，`1-2-4` 表示多个一级类目，`1(1,3,4)-2` 表示一级类目 1 下的部分子类目及一级类目 2。

## 8. 调用示例

```bash
curl -sS http://localhost:8000/health

curl -sS http://localhost:8000/api/pc/notes/detail \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.xiaohongshu.com/explore/笔记ID?xsec_token=..."}'

curl -sS http://localhost:8000/api/pc/search/notes \
  -H 'Content-Type: application/json' \
  -d '{"query":"咖啡","require_num":10}'
```

Python：

```python
import requests

response = requests.post(
    "http://localhost:8000/api/pc/search/users",
    json={"query": "摄影", "require_num": 10},
    timeout=120,
)
response.raise_for_status()
payload = response.json()
if not payload["success"]:
    raise RuntimeError(payload["message"])
print(payload["data"])
```

## 9. 兼容路径

旧版的 `/api/note`、`/api/notes`、`/api/search` 仍可调用，分别对应 `/api/pc/notes/detail`、`/api/pc/notes/batch`、`/api/pc/search/notes`，但不再显示在 OpenAPI 文档中。新接入请使用 `/api/pc/*` 路径。

## 10. 部署建议

- 服务包含带登录态的读写接口，不应直接暴露到公网；应在反向代理或 API 网关增加 TLS、身份认证、访问控制和限流。
- 不要把 `.env`、Cookie、含 `xsec_token` 的日志提交到版本库。
- 单实例内复用签名状态。生产环境先使用一个 worker；多 worker 会各自建立独立状态和请求序列。
- 上游接口可能出现风控、Cookie 失效或结构变化。遇到 `success=false` 时先查看 `message`，再更新 Cookie 或检查服务日志。

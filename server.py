import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

app = FastAPI(
    title="Spider_XHS API",
    version="1.0.0",
)


COOKIES = os.environ.get("COOKIES")

if not COOKIES:
    raise RuntimeError("COOKIES environment variable is required")


auth = XHSPcAuth.from_cookie(COOKIES)
api = XHS_Apis(auth).bootstrap()


class NoteRequest(BaseModel):
    url: str


class SearchRequest(BaseModel):
    keyword: str
    count: int = 20


@app.get("/health")
async def health():
    return {
        "success": True,
        "status": "ok",
    }


@app.post("/api/note")
async def get_note(req: NoteRequest):
    try:
        success, message, data = api.get_note_info(req.url)

        return {
            "success": success,
            "message": message,
            "data": data,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@app.post("/api/search")
async def search(req: SearchRequest):
    try:
        success, message, data = api.search_some_note(
            req.keyword,
            req.count,
        )

        return {
            "success": success,
            "message": message,
            "data": data,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

import os
import socketio
import engineio

from uvicorn.server import logger
from http.cookies import SimpleCookie
from fastapi import FastAPI, Path, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, PlainTextResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.middleware.gzip import GZipMiddleware

APP = FastAPI()
TEMPLATES = Jinja2Templates(directory="templates")

APP.add_middleware(GZipMiddleware, minimum_size=1000)
APP.mount("/static", StaticFiles(directory="static"), name="static")

if REDIS_URL := os.getenv("REDIS_URL"):
    logger.info("REDIS_URL found.")
    mgr = socketio.AsyncRedisManager(REDIS_URL)
    SIO = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", client_manager=mgr)
else:
    logger.info("REDIS_URL not found.")
    SIO = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

APP.mount("/socket.io", engineio.ASGIApp(engineio_server=SIO, engineio_path=""))


@APP.get("/{room_id}/{channel_id}/{file_id}/{file_name}", response_class=HTMLResponse)
async def root(request: Request,
               file_name: str = Path(default="", regex=r".*\.mp4$"),
               room_id: str = Path(default="", regex=r"^[0-9]{10}$"),
               channel_id: str = Path(default="", regex="^[0-9]{18}$"),
               file_id: str = Path(default="", regex=r"^[0-9]{18}$")
               ):
    assert file_name and room_id and channel_id and file_id
    video_url = f"https://cdn.discordapp.com/attachments/{channel_id}/{file_id}/{file_name}"
    cookies = {"room_id": room_id}
    response = TEMPLATES.TemplateResponse("index.html", {"request": request, "video_url": video_url})
    for k, v in cookies.items():
        response.set_cookie(k, v)
    return response


@SIO.on("connect")
async def handle_connect(sid: str, request: dict):
    try:
        simple_cookie = SimpleCookie()
        simple_cookie.load(request["HTTP_COOKIE"])
        room = simple_cookie["room_id"].value
    except (KeyError, ValueError):
        logger.error(f"Error on retrieving cookie from client {sid}, disconnecting...")
        await SIO.disconnect(sid)
    else:
        logger.info(f'Client {sid} connected. Joining room {room}.')
        SIO.enter_room(sid, room)
        async with SIO.session(sid) as session:
            session["room"] = room


@SIO.on("disconnect")
async def handle_disconnect(sid: str):
    logger.info(f"Client {sid} left.")
    async with SIO.session(sid) as session:
        room = session["room"]
        await SIO.emit("client_left", data=sid, room=room)
        SIO.leave_room(sid, room)


@SIO.on("event_mouse")
async def handle_mouse_event(sid: str, msg: dict):
    try:
        msg.update({"client_id": sid})
        async with SIO.session(sid) as session:
            await SIO.emit("event_mouse", data=msg, room=session["room"])
    except Exception:
        pass


@SIO.on("event_video")
async def handle_event_video(sid: str, msg: dict):
    try:
        msg.update({"client_id": sid})
        async with SIO.session(sid) as session:
            await SIO.emit("event_video", data=msg, room=session["room"], skip_sid=sid)
    except Exception:
        pass


@SIO.on("key_up")
async def handle_key_up(sid, msg):
    try:
        msg.update({"client_id": sid})
        async with SIO.session(sid) as session:
            await SIO.emit('key_up', msg, room=session["room"])
    except Exception:
        pass


@SIO.on('mouse_dblclk')
async def handle_dblclk(sid, msg):
    msg['client_id'] = sid
    async with SIO.session(sid) as session:
        await SIO.emit("mouse_dblclk", data=msg, room=session["room"])


@SIO.on("delete_all")
async def handle_delete_all(sid):
    async with SIO.session(sid) as session:
        await SIO.emit('delete_all', room=session["room"])


def get_members(room: str, namespace="/") -> list[str]:
    try:
        return list(SIO.manager.rooms[namespace][room].keys())
    except KeyError:
        return []


@APP.get("/favicon.ico")
async def handle_favicon():
    return FileResponse("static/favicon.ico", media_type="image/x-icon")


@APP.exception_handler(RequestValidationError)
async def request_validation_error_handler(request, exc):
    return JSONResponse({"status": "error", "msg": "Invalid url parameter(s)."}, status_code=400)

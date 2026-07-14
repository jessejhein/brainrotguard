"""Child-facing playlist browsing routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.shared import templates
from web.deps import get_child_store
from web.helpers import base_ctx

router = APIRouter()


@router.get("/playlists", response_class=HTMLResponse)
async def playlists_page(request: Request):
    """List native playlists for the current child."""
    cs = get_child_store(request)
    playlists = cs.get_playlists()
    return templates.TemplateResponse(request, "playlists.html", {
        **base_ctx(request),
        "playlists": playlists,
    })


@router.get("/playlists/{playlist_id}", response_class=HTMLResponse)
async def playlist_detail_page(request: Request, playlist_id: int):
    """Show one native playlist and its ordered items."""
    cs = get_child_store(request)
    playlist = cs.get_playlist(playlist_id)
    if not playlist:
        return RedirectResponse(url="/playlists", status_code=303)
    items = cs.get_playlist_items(playlist_id)
    return templates.TemplateResponse(request, "playlist_detail.html", {
        **base_ctx(request),
        "playlist": playlist,
        "items": items,
    })

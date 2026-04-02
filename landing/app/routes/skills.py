"""Skills authoring routes — list, create, edit, delete guidance skills."""

from __future__ import annotations

import os
from pathlib import Path

import markdown
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..skills import SkillsManager

router = APIRouter(prefix="/skills")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# Skills directory: from env var, or fallback to repo structure.
_skills_dir = Path(os.environ.get("SUS_SKILLS_DIR", str(Path(__file__).resolve().parent.parent.parent.parent / "claude" / "skills")))
_manager = SkillsManager(str(_skills_dir))


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def skills_list(request: Request) -> HTMLResponse:
    """Render the skills list page."""
    skills = _manager.list_skills()
    return _templates.TemplateResponse(
        request,
        "skills_list.html",
        context={"skills": skills},
    )


@router.get("/new", response_class=HTMLResponse)
async def skills_new(request: Request) -> HTMLResponse:
    """Render the create-new-skill form."""
    return _templates.TemplateResponse(
        request,
        "skill_editor.html",
        context={"mode": "create", "skill": None, "errors": []},
    )


@router.get("/guide", response_class=HTMLResponse)
async def skills_guide(request: Request) -> HTMLResponse:
    """Render the AUTHORING.md guide as HTML."""
    skill = _manager.get_skill("AUTHORING")
    body_html = ""
    if skill:
        body_html = markdown.markdown(
            skill["content"],
            extensions=["tables", "fenced_code"],
        )
    return _templates.TemplateResponse(
        request,
        "skill_view.html",
        context={
            "skill_name": "AUTHORING",
            "content_html": body_html,
            "is_guide": True,
        },
    )


@router.get("/{name}", response_class=HTMLResponse)
async def skills_view(request: Request, name: str) -> HTMLResponse:
    """Render a single skill as HTML."""
    skill = _manager.get_skill(name)
    if skill is None:
        return HTMLResponse(status_code=404, content="Skill not found")
    body_html = markdown.markdown(
        skill["content"],
        extensions=["tables", "fenced_code"],
    )
    return _templates.TemplateResponse(
        request,
        "skill_view.html",
        context={
            "skill_name": name,
            "content_html": body_html,
            "is_guide": False,
        },
    )


@router.get("/{name}/edit", response_class=HTMLResponse)
async def skills_edit(request: Request, name: str) -> HTMLResponse:
    """Render the edit form for an existing skill."""
    skill = _manager.get_skill(name)
    if skill is None:
        return HTMLResponse(status_code=404, content="Skill not found")
    return _templates.TemplateResponse(
        request,
        "skill_editor.html",
        context={"mode": "edit", "skill": skill, "errors": []},
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@router.post("", response_class=HTMLResponse)
async def skills_create(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Create a new skill from form submission."""
    # Normalise name.
    clean_name = name.strip().lower().replace(" ", "-")
    if not clean_name.endswith(".md"):
        clean_name = f"{clean_name}.md"

    validation = _manager.validate_skill(content)
    if not validation["valid"]:
        return _templates.TemplateResponse(
            request,
            "skill_editor.html",
            context={
                "mode": "create",
                "skill": {"name": clean_name.removesuffix(".md"), "content": content},
                "errors": validation["errors"],
            },
        )

    _manager.save_skill(clean_name, content)
    return RedirectResponse(
        url=f"/skills/{clean_name.removesuffix('.md')}",
        status_code=303,
    )


@router.post("/{name}/update", response_class=HTMLResponse)
async def skills_update(
    request: Request,
    name: str,
    content: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Update an existing skill (POST override for HTML forms)."""
    validation = _manager.validate_skill(content)
    if not validation["valid"]:
        return _templates.TemplateResponse(
            request,
            "skill_editor.html",
            context={
                "mode": "edit",
                "skill": {"name": name, "content": content},
                "errors": validation["errors"],
            },
        )

    _manager.save_skill(f"{name}.md", content)
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.put("/{name}")
async def skills_put(request: Request, name: str) -> RedirectResponse:
    """Update a skill via PUT (JSON or form)."""
    form = await request.form()
    content = str(form.get("content", ""))

    validation = _manager.validate_skill(content)
    if not validation["valid"]:
        return HTMLResponse(status_code=400, content=str(validation["errors"]))

    _manager.save_skill(f"{name}.md", content)
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.delete("/{name}")
async def skills_delete(name: str) -> RedirectResponse | HTMLResponse:
    """Delete a skill."""
    deleted = _manager.delete_skill(name)
    if not deleted:
        return HTMLResponse(status_code=400, content="Cannot delete this skill.")
    return RedirectResponse(url="/skills", status_code=303)


@router.post("/{name}/delete")
async def skills_delete_via_post(name: str) -> RedirectResponse | HTMLResponse:
    """Delete a skill via POST (for HTML form compatibility)."""
    deleted = _manager.delete_skill(name)
    if not deleted:
        return HTMLResponse(status_code=400, content="Cannot delete this skill.")
    return RedirectResponse(url="/skills", status_code=303)

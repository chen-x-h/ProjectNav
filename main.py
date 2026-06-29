import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from nicegui import ui

def _env_path(key: str, default: Path) -> Path:
    val = os.environ.get(key)
    return Path(val) if val else default

BASE_DIR = Path(os.environ.get("PROJECT_BASE_DIR", Path(__file__).parent))
DATA_FILE = _env_path("PROJECTS_FILE", BASE_DIR / "projects.json")
LOG_FILE = _env_path("LOG_FILE", Path(tempfile.gettempdir()) / "project_manager.log")
TEMPLATE_FILE = _env_path("START_TEMPLATE", BASE_DIR / "start_script_template.txt")
STOP_TEMPLATE_FILE = _env_path("STOP_TEMPLATE", BASE_DIR / "stop_script_template.txt")
SORT_FILE = _env_path("SORT_FILE", BASE_DIR / "sort_order.json")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "20001"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("project_manager")


def load_projects() -> list[dict]:
    if not DATA_FILE.exists():
        logger.info("数据文件 %s 不存在，初始化为空列表", DATA_FILE)
        return []
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
        logger.info("已加载 %d 个项目 from %s", len(data), DATA_FILE)
        return data


def save_projects(projects: list[dict]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)
    logger.info("已保存 %d 个项目到 %s", len(projects), DATA_FILE)


def load_sort_order() -> dict:
    if not SORT_FILE.exists():
        return {"categories": [], "projects": {}}
    with open(SORT_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_sort_order(order: dict):
    with open(SORT_FILE, "w", encoding="utf-8") as f:
        json.dump(order, f, indent=2, ensure_ascii=False)


def run_script(path: str) -> str:
    if not path or not os.path.isfile(path):
        logger.warning("脚本文件不存在: %s", path)
        return "脚本文件不存在"
    try:
        logger.info("执行脚本: %s", path)
        if sys.platform == "win32":
            result = subprocess.run(["cmd", "/c", path], capture_output=True, text=True, timeout=30)
        else:
            result = subprocess.run(["bash", path], capture_output=True, text=True, timeout=30)
        out = result.stdout.strip() or result.stderr.strip() or "执行完成（无输出）"
        logger.info("脚本 %s 执行完成, 返回码 %d", path, result.returncode)
        return out
    except subprocess.TimeoutExpired:
        logger.error("脚本执行超时: %s", path)
        return "执行超时（30s）"
    except Exception as e:
        logger.error("脚本执行出错 %s: %s", path, e)
        return f"执行出错: {e}"


async def check_url(url: str) -> tuple[bool, str]:
    if not url:
        logger.warning("检测状态跳过：未配置地址")
        return False, "未配置地址"
    try:
        logger.info("检测项目状态: %s", url)
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.get(url)
            logger.info("状态检测完成 %s -> HTTP %d", url, resp.status_code)
            return True, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        logger.warning("状态检测连接失败: %s", url)
        return False, "连接失败"
    except httpx.TimeoutException:
        logger.warning("状态检测超时: %s", url)
        return False, "请求超时"
    except Exception as e:
        logger.error("状态检测异常 %s: %s", url, e)
        return False, str(e)


# ---------- state ----------
projects = load_projects()
status_map: dict[int, Optional[bool]] = {}
search_text = ""
filter_auto_only = False
filter_category = ""
filter_tag = ""

_next_id = 0
for p in projects:
    if "id" not in p:
        p["id"] = _next_id
        _next_id += 1
    else:
        _next_id = max(_next_id, p["id"] + 1)
    p.setdefault("category", "未分类")
    if not p["category"]:
        p["category"] = "未分类"
    p.setdefault("auto_start", False)
    p.setdefault("extra_links", [])
    p.setdefault("tags", [])



def get_project(pid: int) -> Optional[dict]:
    for p in projects:
        if p["id"] == pid:
            return p
    return None


def all_categories() -> list[str]:
    cats = sorted({p.get("category", "未分类") for p in projects})
    return cats


def all_tags() -> list[str]:
    ts = set()
    for p in projects:
        ts.update(p.get("tags", []))
    return sorted(ts)


def filtered_projects() -> list[dict]:
    result = projects
    if search_text:
        result = [p for p in result if search_text.lower() in p.get("name", "").lower()]
    if filter_auto_only:
        result = [p for p in result if p.get("auto_start")]
    if filter_category:
        result = [p for p in result if p.get("category", "未分类") == filter_category]
    if filter_tag:
        result = [p for p in result if filter_tag in p.get("tags", [])]
    return result


def grouped_projects(proj_list: list[dict]) -> list[tuple[str, list[dict]]]:
    sort_order = load_sort_order()
    cat_order = sort_order.get("categories", [])
    proj_order = sort_order.get("projects", {})
    groups: dict[str, list[dict]] = {}
    for p in proj_list:
        cat = p.get("category", "未分类")
        groups.setdefault(cat, []).append(p)
    def cat_key(c):
        i = cat_order.index(c) if c in cat_order else -1
        return (0, i) if i >= 0 else (1, c)
    sorted_cats = sorted(groups.keys(), key=cat_key)
    result = []
    for c in sorted_cats:
        cat_projects = groups[c]
        order = proj_order.get(c, [])
        def proj_key(p):
            i = order.index(p["id"]) if p["id"] in order else -1
            return (0, i) if i >= 0 else (1, p.get("name", "").lower())
        cat_projects.sort(key=proj_key)
        result.append((c, cat_projects))
    return result


def refresh():
    container.clear()
    build_ui()


def build_ui():
    global filter_category, filter_tag
    with container:
        with ui.row().classes("w-full items-center mb-2"):
            search_input = ui.input("搜索项目名称", value=search_text).props("outlined dense clearable").classes("flex-1")

            def do_search(*_):
                global search_text
                search_text = search_input.value
                refresh()

            search_input.on("keyup.enter", do_search)
            search_input.on("blur", do_search)

            def toggle_auto_filter():
                global filter_auto_only
                filter_auto_only = not filter_auto_only
                refresh()

            auto_filter_btn = ui.button("仅自启动", on_click=toggle_auto_filter, icon="power_settings_new")
            if not filter_auto_only:
                auto_filter_btn.props("flat")
            else:
                auto_filter_btn.props("flat color=positive")

            cats = [""] + all_categories()
            if filter_category and filter_category not in cats:
                filter_category = ""
            def on_cat_filter(e):
                global filter_category
                filter_category = e.value
                refresh()
            ui.select(cats, value=filter_category, label="全部分类", on_change=on_cat_filter).props("outlined dense").classes("w-40")

            tag_opts = [""] + all_tags()
            if filter_tag and filter_tag not in tag_opts:
                filter_tag = ""
            def on_tag_filter(e):
                global filter_tag
                filter_tag = e.value
                refresh()
            ui.select(tag_opts, value=filter_tag, label="全部标签", on_change=on_tag_filter).props("outlined dense").classes("w-40")

            async def do_batch_auto_start():
                ui.notify("开始批量自启动...", type="info", close_button=True)
                await batch_auto_start()

            ui.button("批量自启动", on_click=do_batch_auto_start, icon="play_arrow").props("flat")

            async def check_all():
                ui.notify("开始检测所有项目...", type="info", close_button=True)
                for p in projects:
                    if p.get("url"):
                        ok, msg = await check_url(p["url"])
                        status_map[p["id"]] = ok
                ui.notify("检测完成", type="positive")
                refresh()

            ui.button("检测所有", on_click=check_all, icon="travel_explore").props("flat")
            ui.button("添加项目", on_click=add_project, icon="add")
            ui.button("排序", on_click=open_sort_dialog, icon="reorder").props("flat")

        filtered = filtered_projects()
        groups = grouped_projects(filtered)

        for cat_name, cat_projects in groups:
            ui.label(cat_name).classes("text-xl font-bold mt-4 mb-2")

            for p in cat_projects:
                pid = p["id"]
                with ui.card().classes("w-full mb-2"):
                    with ui.row().classes("w-full items-start"):
                        s = status_map.get(pid)
                        if s is True:
                            dot = "bg-green-500"
                        elif s is False:
                            dot = "bg-red-500"
                        else:
                            dot = "bg-gray-400"
                        ui.element("div").classes(f"w-3 h-3 rounded-full mt-1.5 {dot} shrink-0")

                        with ui.column().classes("flex-1"):
                            with ui.row().classes("items-center gap-1"):
                                ui.markdown(f"**{p['name']}**").classes("text-lg")
                                if p.get("auto_start"):
                                    ui.label("自启动").classes("text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded inline-block")
                            for t in p.get("tags", []):
                                ui.label(t).classes("text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded inline-block")
                            if p.get("description"):
                                ui.markdown(p["description"])
                            if p.get("url"):
                                href = p["url"] if "://" in p["url"] else f"http://{p['url']}"
                                ui.link(p["url"], href, new_tab=True)
                            for link in p.get("extra_links", []):
                                if link.get("url"):
                                    href = link["url"] if "://" in link["url"] else f"http://{link['url']}"
                                    label = f"{link.get('desc', '链接')} -> {link['url']}"
                                    ui.link(label, href, new_tab=True).classes("text-sm")

                        with ui.row().props("tight"):
                            async def check(p=p, pid=pid):
                                ok, msg = await check_url(p.get("url", ""))
                                status_map[pid] = ok
                                ui.notify(f"{'运行中' if ok else '未运行'} ({msg})", type="positive" if ok else "negative")
                                refresh()
                            ui.button("检测状态", on_click=check).props("flat dense")

                            async def start(p=p):
                                out = run_script(p.get("start_script", ""))
                                ui.notify(f"启动脚本输出:\n{out}", type="positive", multi_line=True)
                            if p.get("start_script"):
                                ui.button("启动", on_click=start).props("flat dense color=positive")

                            async def stop(p=p):
                                out = run_script(p.get("stop_script", ""))
                                ui.notify(f"停止脚本输出:\n{out}", type="negative", multi_line=True)
                            if p.get("stop_script"):
                                ui.button("停止", on_click=stop).props("flat dense color=negative")

                            ui.button("编辑", on_click=lambda pid=pid: edit_project(pid)).props("flat dense")
                            ui.button("删除", on_click=lambda pid=pid: delete_project(pid)).props("flat dense color=grey")

        if not filtered:
            ui.label("暂无项目").classes("text-gray-400 text-center w-full mt-8")


def open_sort_dialog():
    sort_order = load_sort_order()

    def sync_cats():
        cats = all_categories()
        order = sort_order.setdefault("categories", [])
        order[:] = [c for c in order if c in cats]
        for c in cats:
            if c not in order:
                order.append(c)

    def sync_projs(cat: str) -> list:
        cat_ids = [p["id"] for p in projects if p.get("category", "未分类") == cat]
        order = sort_order.setdefault("projects", {}).setdefault(cat, [])
        order[:] = [pid for pid in order if pid in cat_ids]
        for pid in cat_ids:
            if pid not in order:
                order.append(pid)
        return order

    sync_cats()

    with ui.dialog() as dlg, ui.card().classes("w-[600px] max-w-full"):
        title = ui.label("分类排序").classes("text-xl mb-4")
        container = ui.column().classes("w-full gap-1")

        def show_cats():
            container.clear()
            title.set_text("分类排序")
            cats = sort_order["categories"]
            with container:
                for i, c in enumerate(cats):
                    with ui.row().classes("w-full items-center p-2 bg-gray-50 rounded border"):
                        def move_up(idx=i):
                            if idx > 0:
                                cats[idx], cats[idx-1] = cats[idx-1], cats[idx]
                                save_sort_order(sort_order)
                                show_cats()
                        def move_down(idx=i):
                            if idx < len(cats) - 1:
                                cats[idx], cats[idx+1] = cats[idx+1], cats[idx]
                                save_sort_order(sort_order)
                                show_cats()
                        ui.button(icon="arrow_upward", on_click=move_up).props("flat dense round size-xs")
                        ui.button(icon="arrow_downward", on_click=move_down).props("flat dense round size-xs")
                        ui.label(c).classes("flex-1 font-bold")
                        ui.button(icon="chevron_right", on_click=lambda cat=c: show_projs(cat)).props("flat dense")

        def show_projs(cat: str):
            proj_order = sync_projs(cat)
            container.clear()
            title.set_text(f"排序项目 - {cat}")
            with container:
                ui.button("← 返回分类排序", on_click=show_cats).props("flat")
                for i, pid in enumerate(proj_order):
                    p = get_project(pid)
                    if not p:
                        continue
                    with ui.row().classes("w-full items-center p-2 bg-gray-50 rounded border"):
                        def move_up(idx=i, _cat=cat):
                            ord = sort_order["projects"][_cat]
                            if idx > 0:
                                ord[idx], ord[idx-1] = ord[idx-1], ord[idx]
                                save_sort_order(sort_order)
                                show_projs(_cat)
                        def move_down(idx=i, _cat=cat):
                            ord = sort_order["projects"][_cat]
                            if idx < len(ord) - 1:
                                ord[idx], ord[idx+1] = ord[idx+1], ord[idx]
                                save_sort_order(sort_order)
                                show_projs(_cat)
                        ui.button(icon="arrow_upward", on_click=move_up).props("flat dense round size-xs")
                        ui.button(icon="arrow_downward", on_click=move_down).props("flat dense round size-xs")
                        ui.label(p["name"]).classes("flex-1")

        show_cats()

        with ui.row().classes("w-full justify-end"):
            ui.button("关闭", on_click=lambda: (dlg.close(), refresh()))
    dlg.open()


def add_project():
    open_form({
        "name": "", "description": "", "url": "", "category": "未分类",
        "start_script": "", "stop_script": "", "auto_start": False, "extra_links": [], "tags": [],
    }, None)


def edit_project(pid: int):
    p = get_project(pid)
    if p:
        open_form(p.copy(), pid)


def show_template_dialog(title: str, filepath: Path):
    if not filepath.exists():
        ui.notify(f"模板文件 {filepath} 不存在", type="warning", close_button=True)
        return
    content = filepath.read_text(encoding="utf-8")
    with ui.dialog() as dlg, ui.card().classes("w-[600px] max-w-full"):
        ui.label(title).classes("text-lg mb-2")
        ui.textarea("", value=content).props("rows=15 readonly").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("关闭", on_click=dlg.close).props("flat")
    dlg.open()


def open_form(data: dict, pid: Optional[int]):
    links = data.get("extra_links", [])

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-[800px]").style("max-height: 85vh; overflow-y: auto;"):
        ui.label("编辑项目" if pid is not None else "添加项目").classes("text-xl mb-4")
        name = ui.input("项目名称", value=data["name"]).classes("w-full")
        with ui.row().classes("w-full items-center gap-1"):
            cat = ui.input("分类", value=data.get("category", "未分类")).classes("flex-1")
            with ui.button(icon="arrow_drop_down", on_click=lambda: cat_menu.open()).props("flat dense"):
                with ui.menu() as cat_menu:
                    for c in all_categories():
                        ui.menu_item(c, on_click=lambda v=c: (setattr(cat, 'value', v), cat_menu.close()))
        url = ui.input("项目地址", value=data.get("url", "")).classes("w-full")

        with ui.row().classes("w-full items-center gap-2"):
            start = ui.input("启动脚本路径", value=data.get("start_script", "")).classes("flex-1")
            ui.button("模板", on_click=lambda: show_template_dialog("启动脚本模板", TEMPLATE_FILE), icon="description").props("flat dense")

        with ui.row().classes("w-full items-center gap-2"):
            stop = ui.input("停止脚本路径", value=data.get("stop_script", "")).classes("flex-1")
            ui.button("模板", on_click=lambda: show_template_dialog("停止脚本模板", STOP_TEMPLATE_FILE), icon="description").props("flat dense")

        with ui.expansion("描述（Markdown）", icon="description").classes("w-full"):
            desc = ui.textarea("", value=data.get("description", "")).props("rows=10").classes("w-full")

        auto_start = ui.checkbox("启动时自动运行启动脚本", value=data.get("auto_start", False))

        # Tags
        tags = data.get("tags", [])
        ui.separator().classes("my-2")
        ui.label("标签").classes("text-lg")
        with ui.row().classes("w-full items-center gap-2"):
            tag_input = ui.input("输入标签后回车").classes("flex-1").on("keyup.enter", lambda: add_tag())
            def add_tag():
                val = tag_input.value.strip()
                if val and val not in tags:
                    tags.append(val)
                    rebuild_tags()
                tag_input.value = ""
            ui.button("添加", on_click=add_tag, icon="add").props("flat")
        tags_container = ui.row().classes("w-full gap-1 flex-wrap")
        def rebuild_tags():
            tags_container.clear()
            with tags_container:
                for t in tags[:]:
                    with ui.element("span").classes("inline-flex items-center gap-1 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded"):
                        ui.label(t)
                        ui.icon("close").on("click", lambda v=t: (tags.remove(v), rebuild_tags())).props("flat dense cursor-pointer").classes("text-xs hover:text-red-500")
        rebuild_tags()

        # Extra links
        ui.separator().classes("my-2")
        ui.label("附属链接").classes("text-lg")
        links_container = ui.column().classes("w-full gap-1")

        def rebuild_links():
            links_container.clear()
            with links_container:
                for i, link in enumerate(links):
                    with ui.row().classes("w-full items-center gap-2"):
                        d = ui.input("描述", value=link.get("desc", ""),
                                     on_change=lambda e, idx=i: links[idx].__setitem__("desc", e.value)).classes("flex-1")
                        u = ui.input("URL", value=link.get("url", ""),
                                     on_change=lambda e, idx=i: links[idx].__setitem__("url", e.value)).classes("flex-1")
                        ui.button("", on_click=lambda idx=i: (links.pop(idx), rebuild_links()), icon="delete").props("flat dense color=negative")

        rebuild_links()
        ui.button("添加链接", on_click=lambda: (links.append({"desc": "", "url": ""}), rebuild_links()), icon="add").props("flat")

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("取消", on_click=dialog.close).props("flat")
            ui.button("保存", on_click=lambda: save_form(dialog, pid, name.value, desc.value, url.value, cat.value, start.value, stop.value, auto_start.value, links, tags))

    dialog.open()


def save_form(dialog, pid, name, description, url, category, start_script, stop_script, auto_start, extra_links, tags):
    global _next_id, projects
    data = {
        "id": pid if pid is not None else _next_id,
        "name": name, "description": description,
        "url": url, "category": category,
        "start_script": start_script, "stop_script": stop_script,
        "auto_start": auto_start, "extra_links": extra_links, "tags": tags,
    }
    if pid is not None:
        for i, p in enumerate(projects):
            if p["id"] == pid:
                projects[i] = data
                logger.info("更新项目 %d: %s (自启动=%s)", pid, name, auto_start)
                break
    else:
        projects.append(data)
        logger.info("新增项目 %d: %s (自启动=%s)", _next_id, name, auto_start)
        _next_id += 1
    save_projects(projects)
    dialog.close()
    refresh()


def delete_project(pid: int):
    global projects
    name = next((p["name"] for p in projects if p["id"] == pid), "?")
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)
    status_map.pop(pid, None)
    logger.info("删除项目 %d: %s", pid, name)
    refresh()


async def _try_start(p: dict) -> str:
    url = p.get("url", "")
    if url:
        ok, _ = await check_url(url)
        if ok:
            msg = f"地址 {url} 已可用，跳过执行"
            logger.info("自启动跳过 %s: %s", p["name"], msg)
            return msg
    return await asyncio.to_thread(run_script, p["start_script"])


async def _run_all_auto_starts(targets: list[dict]) -> list[tuple[str, str]]:
    logger.info("自启动: %d 个项目", len(targets))
    results = []
    for p in targets:
        out = await _try_start(p)
        results.append((p["name"], out))
        logger.info("自启动 %s: %s", p["name"], out)
    return results


async def batch_auto_start():
    targets = [p for p in projects if p.get("auto_start") and p.get("start_script")]
    if not targets:
        ui.notify("没有配置自启动的项目", type="warning")
        return
    results = await _run_all_auto_starts(targets)
    for name, out in results:
        ui.notify(f"{name}: {out}", type="positive", close_button=True)
    ui.notify("批量自启动完成", type="positive")


# ---------- main ----------
container = ui.column().classes("w-full max-w-4xl mx-auto p-4")
ui.query("body").classes("bg-gray-50")
build_ui()

# 环境变量标记确保进程内只执行一次自启动（script 模式下模块可能被重新加载）
if not os.environ.get("_PROJECT_NAV_AUTO_START_DONE"):
    os.environ["_PROJECT_NAV_AUTO_START_DONE"] = "1"
    targets = [p for p in projects if p.get("auto_start") and p.get("start_script")]
    if targets:
        asyncio.run(_run_all_auto_starts(targets))

ui.run(
    title="项目管理器",
    host=HOST,
    port=PORT,
    reload=False,
)


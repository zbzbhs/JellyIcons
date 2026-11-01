"""Read desktop item bounds through UI Automation.

No explorer-memory access, no SendMessage, no registry access, no shell-window
modification: only read-only UI Automation calls. Coordinates are physical
screen pixels.

If this process runs at a lower integrity level than explorer (e.g. inside
some sandboxes), UIPI silently hides the ListView children. The reader
detects that case and raises IntegrityError so the UI can tell the user to
launch from a normal shell instead.
"""
from __future__ import annotations

import ctypes
import sys
import types
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [
    wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
]

UIA_CLASS_NAME = 30012  # UIA_ClassNamePropertyId
TREE_SCOPE_CHILDREN = 2
DESKTOP_LIST_NAMES = {"folderview", "桌面", "desktop"}


class IntegrityError(RuntimeError):
    """Raised when UIPI blocks UI Automation from seeing desktop items."""


@dataclass(frozen=True, slots=True)
class DesktopIcon:
    key: str
    name: str
    rect: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def _bootstrap_comtypes() -> str:
    """Import comtypes.client with the code cache inside this workspace.

    ``import comtypes.client`` normally creates a generated-code directory
    under ``%APPDATA%`` (denied outside the sandbox workspace). Preload
    ``comtypes.client._code_cache`` standalone, patch ``_find_gen_dir`` to a
    workspace directory, and stub ``comtypes.gen`` before the package
    ``__init__`` runs.
    """
    cache = Path(__file__).resolve().parents[1] / ".cache" / "comtypes"
    cache.mkdir(parents=True, exist_ok=True)
    if "comtypes.client._code_cache" in sys.modules:
        return str(cache)

    import importlib.util

    import comtypes

    comtypes_dir = Path(comtypes.__file__).parent
    spec = importlib.util.spec_from_file_location(
        "comtypes.client._code_cache", comtypes_dir / "client" / "_code_cache.py"
    )
    code_cache = importlib.util.module_from_spec(spec)
    sys.modules["comtypes.client._code_cache"] = code_cache
    spec.loader.exec_module(code_cache)
    code_cache._find_gen_dir = lambda: str(cache)

    gen = types.ModuleType("comtypes.gen")
    gen.__path__ = [str(cache)]
    sys.modules["comtypes.gen"] = gen
    comtypes.gen = gen  # generated submodules reference this attribute

    import comtypes.client  # noqa: F401  (runs with the patched cache)

    return str(cache)


class DesktopReader:
    """Lazy, read-only UI Automation desktop reader."""

    def __init__(self) -> None:
        self._automation = None
        self._root = None

    def _initialize(self) -> None:
        if self._automation is not None:
            return
        _bootstrap_comtypes()
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
        self._automation = comtypes.client.CreateObject(
            uia_module.CUIAutomation, interface=uia_module.IUIAutomation
        )
        self._root = self._automation.GetRootElement()

    def _condition(self, class_name: str):
        return self._automation.CreatePropertyCondition(
            UIA_CLASS_NAME, class_name
        )

    def _desktop_list(self):
        """Find the desktop SysListView32 element.

        Purely read-only: locate the classic Progman→SHELLDLL_DefView→
        SysListView32 handle chain with FindWindow/FindWindowEx, then wrap
        the ListView handle in a UIA element (ElementFromHandle). UIA tree
        walking from the root element turned out unreliable on real
        desktops (returns 0 items even at Medium integrity), while the
        handle chain + ElementFromHandle works.
        """
        self._initialize()
        list_hwnd = self._find_listview_hwnd()
        if list_hwnd:
            element = self._automation.ElementFromHandle(list_hwnd)
            if element is not None:
                return element
        # Fallback: original UIA tree walk (kept for non-classical shells).
        shell_views: list = []
        for host_class in ("Progman", "WorkerW"):
            hosts = self._root.FindAll(
                TREE_SCOPE_CHILDREN, self._condition(host_class)
            )
            for index in range(hosts.Length):
                host = hosts.GetElement(index)
                views = host.FindAll(
                    TREE_SCOPE_CHILDREN, self._condition("SHELLDLL_DefView")
                )
                for view_index in range(views.Length):
                    shell_views.append(views.GetElement(view_index))
        for view in shell_views:
            lists = view.FindAll(
                TREE_SCOPE_CHILDREN, self._condition("SysListView32")
            )
            for list_index in range(lists.Length):
                desktop_list = lists.GetElement(list_index)
                if (desktop_list.CurrentName or "").lower() in DESKTOP_LIST_NAMES:
                    return desktop_list
        return None

    def _find_listview_hwnd(self) -> int:
        progman = user32.FindWindowW("Progman", None)
        if not progman:
            return 0
        defview = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
        if not defview:
            # WorkerW variant (wallpaper engines host the DefView there)
            worker = user32.FindWindowExW(progman, 0, "WorkerW", None)
            while worker:
                defview = user32.FindWindowExW(
                    worker, 0, "SHELLDLL_DefView", None)
                if defview:
                    break
                worker = user32.FindWindowExW(
                    progman, worker, "WorkerW", None)
        if not defview:
            return 0
        listview = user32.FindWindowExW(defview, 0, "SysListView32", None)
        if listview and (user32.GetWindowTextLengthW(listview) or True):
            return listview or 0
        return 0

    def snapshot(self) -> list[DesktopIcon]:
        """Return current desktop items as (key, name, rect) records.

        Raises IntegrityError when UIPI (lower integrity level than
        explorer) hides the whole desktop tree, which is how it manifests.
        """
        desktop_list = self._desktop_list()
        if desktop_list is None:
            if self._root.FindAll(
                TREE_SCOPE_CHILDREN, self._automation.CreateTrueCondition()
            ).Length == 0:
                raise IntegrityError(
                    "UI Automation cannot see the desktop window tree. "
                    "This process probably runs at a lower integrity level "
                    "than explorer (UIPI). Launch from a normal cmd or "
                    "Explorer window, not from a sandboxed session."
                )
            raise IntegrityError(
                "Desktop ListView not found (neither via window handles "
                "nor UIA tree). Is Explorer running? Are desktop icons "
                "enabled (View > Show desktop icons)?"
            )
        items = desktop_list.FindAll(
            TREE_SCOPE_CHILDREN, self._automation.CreateTrueCondition()
        )
        if items.Length == 0:
            raise IntegrityError(
                "UI Automation can see the desktop list but no items. "
                "Either the desktop is empty or UIPI is filtering children; "
                "if icons are visible on screen, launch from a normal cmd "
                "or Explorer window."
            )
        result: list[DesktopIcon] = []
        for index in range(items.Length):
            item = items.GetElement(index)
            bounds = item.CurrentBoundingRectangle
            left, top = int(bounds.left), int(bounds.top)
            right, bottom = int(bounds.right), int(bounds.bottom)
            if right <= left or bottom <= top:
                continue
            label = item.CurrentName or ""
            if not label:
                continue
            result.append(DesktopIcon(label, label, (left, top, right, bottom)))
        return result


if __name__ == "__main__":
    reader = DesktopReader()
    try:
        icons = reader.snapshot()
    except IntegrityError as exc:
        print(f"IntegrityError: {exc}")
    else:
        print(f"count={len(icons)}")
        for icon in icons[:5]:
            print(icon)
    # tree dump for diagnosis
    try:
        reader._initialize()
        print("--- root children ---")
        children = reader._root.FindAll(
            TREE_SCOPE_CHILDREN, reader._automation.CreateTrueCondition())
        for i in range(children.Length):
            el = children.GetElement(i)
            print(f"  [{i}] class={el.CurrentClassName!r} "
                  f"name={el.CurrentName!r} rect={el.CurrentBoundingRectangle}")
    except Exception as exc:
        print(f"tree dump failed: {exc!r}")

# Тест ажиллуулах

## Desktop шаардахгүй шалгалт

Repo-ийн root-оос:

```sh
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
(umask 022; uv run pytest -q --cov=omnimcp --cov-report=term)
uv build
```

Энэ suite бодит worker subprocess, Unix socket, MCP stdio, PTY болон түр
файлуудыг шалгана. Coverage floor **84%**; worker/CLI subprocess coverage
идэвхтэй байх ёстой. `umask 022` нь стандарт орчин дахь permission-ий
хамаарлыг илрүүлнэ. `e2e`, `background` marker-тай тестүүд default-аар
**deselected** болно; тэдгээрийг passed гэж тооцохгүй.

## Амьд Hyprland тест — зөвхөн тусгаарласан VM дотор

Хэрэглэгчийн өдөр тутмын desktop дээр дараах командыг бүү ажиллуул. Тестүүд
цонх нээж/хааж, workspace, focus болон бодит keyboard/pointer-ийг удирдана.
Disposable VM дотор эх код, dev dependencies болон тестүүдэд хэрэгтэй
Hyprland, grim, wtype, kitty, yad, AT-SPI орчныг бэлдэж, VM-ийн өөрийн
`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`,
`DBUS_SESSION_BUS_ADDRESS`-ийг ашиглана. Host session-ийн утгыг дамжуулахгүй.

VM дотор ажиллаж буй Hyprland session-оос:

```sh
uv run pytest -q -m "e2e or background"
```

Ажилласан/passed, skipped, failed тоог тус тусад нь тайлагна. Амьд session эсвэл
шаардлагатай апп байхгүйн улмаас skipped болсон нь desktop validation биш.
Compositor teardown-ийн exit code, JSON readback болон screenshots-ийг хадгал.
Coverage-гүй энэ тусдаа live run нь үндсэн suite-ийн coverage gate-ийг орлохгүй.

[QEMU acceptance harness](../scripts/hyprland-vm/README.md) нь бодит desktop
үйлдлүүдийг шалгадаг боловч дээрх pytest selection-ийг автоматаар ажиллуулдаггүй.
Өмнөх тайланд 16 live тест deselected байсан; энэ удаагийн packaging/retention
өөрчлөлт шинэ live desktop validation хийсэн гэсэн үг биш.

## Build-ийн шалгалт

Шинэ wheel нь `omnimcp_linux-<version>-py3-none-any.whl`, sdist нь
`omnimcp_linux-<version>.tar.gz` байна. Metadata-ийн `Name` нь `OmniMCP-linux`;
`OmniMCP`, `omnimcp` хоёр executable болон Python `omnimcp` module хадгалагдана.
sdist дотор `docs/evidence/` байх ёсгүй; raw evidence зөвхөн Git-д үлдэнэ.
Build гарцыг цэвэр түр хавтас/virtualenv дотор шалгаж, хуучин `dist/*`-тэй
хольж дүгнэхгүй.

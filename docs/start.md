# Эхлүүлэх

OmniMCP нь одоогоор PyPI-д нийтлэгдээгүй. GitHub-ийн
`main` салбараас `uv`-ээр суулгана. Энэ нь GitHub-ийн хөгжүүлэлтийн хувилбар.
Linux, Python 3.11 буюу түүнээс шинэ хувилбар, `uv`, Hyprland
Wayland session хэрэгтэй. Desktop-ийн screenshot/input-д `grim`, `wtype`,
`busctl`; UI tree-д AT-SPI bus болон accessibility мэдээлэл гаргадаг апп хэрэгтэй.

```sh
uv tool install --from 'git+https://github.com/yesunbileg/omnimcp.git@main' OmniMCP
OmniMCP --version
OmniMCP doctor
```

Үндсэн команд нь `OmniMCP`; хуучин `omnimcp` команд мөн ажиллана.
Python import, plugin ID, `OMNIMCP_*` тохиргоо болон өгөгдлийн зам өөрчлөгдөхгүй.

Энэ нь branch-ийн одоогийн commit-ийг хэрэглэгчийн `uv` tool орчинд суулгана.
Шалгахдаа `git ls-remote https://github.com/yesunbileg/omnimcp.git refs/heads/main`
ашиглаж branch-ийн commit-ийг баталгаажуул. Branch өөрчлөгдөж болох тул ижил
хувилбарыг дахин суулгахдаа шалгасан commit hash-аар `@<commit>` ref-ийг солино.
Энэ нь хэрэглэгчийн `uv` tool орчинд суулгана; системийн Python-д `sudo`-гоор
суулгах шаардлагагүй. Шинэ хувилбар суулгасны дараа MCP client-ээ дахин холбоно.

## MCP client-д холбох

`OmniMCP`-ийг stdio MCP server болгон бүртгэнэ. Ажиллаж буй Hyprland session-оос
`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`,
`DBUS_SESSION_BUS_ADDRESS` утгуудыг server процесс руу дамжуул. Эдгээр нь
desktop-д хандахад хэрэгтэй; өөр session-ийн утга тааж тохируулж болохгүй.

Эхлэхэд уламжлалт desktop tool-ууд default байдаг. Compact API-г туршихдаа
`args = ["--profile", "compact"]` нэм эсвэл server environment-д
`OMNIMCP_PROFILE=compact` тохируул. Хоёр profile-ийн тухай [боломжууд](features.md)
болон [техникийн гэрээ](CORE.md)-г унш.

## Codex plugin

Энэ checkout доторх plugin-ийг Codex-ийн local marketplace-д бүртгэнэ:

```sh
codex plugin marketplace add /path/to/omnimcp/packaging/codex
codex plugin add omnimcp@omnimcp-local
```

Plugin нь `OMNIMCP_BIN`-ээр runtime executable-ийг зааж болно. Үүнийг өгөөгүй
бол `OmniMCP`-ийг `PATH`-аас олно. Нэмэлт тохиргоог plugin-ийн өөрийн manifest-д
оруул; үндсэн Codex config-д тусдаа `mcp_servers.omnimcp` entry нэмж давхар
бүртгэхгүй. Portable Agent Plugins хувилбарт
`packaging/codex/omnimcp/mcp.json` доторх `env` map-д бодит замаа бич:

```json
"env": {
  "OMNIMCP_BIN": "/absolute/path/to/OmniMCP",
  "OMNIMCP_KANBAN_FILE": "/absolute/path/to/kanban.md"
}
```

Хэрэглэхгүй утгыг хасаж болно. `OMNIMCP_BIN`-ийг өгөөгүй бол `PATH` ашиглана;
Kanban хэрэглэхгүй бол `OMNIMCP_KANBAN_FILE`-ийг оруулахгүй. Codex compatibility
`.mcp.json`-д мөн ижил `env` утгуудыг тохируулж, аль хэдийн байгаа `env_vars`
жагсаалтад session-ийн дөрвөн хувьсагчийг үлдээ. Plugin shim эдгээр утгыг runtime
руу дамжуулна. Plugin суусны дараа шинэ chat нээ.

## Ажиллуулах

```sh
OmniMCP desktop
OmniMCP canvas /absolute/path/Plan.canvas
```

`desktop`-оор session-оо шалга. Kanban тохируулах, аюулгүй байдлын тохиргоо,
буцаалт болон эрхийн хязгаарлалтыг [Тохиргоо](settings.md)-оос үз.

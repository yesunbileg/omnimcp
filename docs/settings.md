# Тохиргоо ба аюулгүй ажиллагаа

MCP server-д тохиргоог environment variable-аар өгнө. Systemd worker ашиглаж
байгаа бол worker-ийн environment-ийг user service drop-in-д тохируул: дараа нь
MCP bridge-д өгсөн утга ажиллаж буй worker-ийн орчныг өөрчилдөггүй. Client-д
`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`,
`DBUS_SESSION_BUS_ADDRESS`-ийг тухайн desktop session-оос дамжуул.

## Environment хувьсагч

| Хувьсагч | Default ба утга |
| --- | --- |
| `OMNIMCP_PROFILE` | `legacy`. `compact` нь шинэ compact MCP API-г сонгоно. CLI-ийн `--profile` үүнийг дарна. |
| `OMNIMCP_READONLY` | Унтраалттай. Яг `1`, `true`, `yes`, `on` (том/жижиг үсэг хамаарахгүй) үед өөрчлөлт хийх үйлдлүүдийг хориглоно. Compact bridge discovery-г шүүж `act`/`workflow` болон cancel-ийг хасна. |
| `OMNIMCP_DRYRUN` | Унтраалттай. `1`, `true`, `yes`, `on` үед шалгалт, guard-уудыг ажиллуулаад нөлөө үүсгэхгүй preview буцаана. |
| `OMNIMCP_CLIPBOARD` | Унтраалттай. `1`, `true`, `yes`, `on` үед clipboard tool-ийг зөвшөөрнө. Clipboard-д нууц үг байж болдог. |
| `OMNIMCP_AUTH_GUARD` | `1` буюу асаалттай. Танигдсан polkit/auth цонхыг удирдахыг хориглоно. `strict`, `2`, `field`, `fields` нь accessibility tree шалгаж ердийн цонхны password талбарт бичихийг мөн хориглоно. |
| `OMNIMCP_ALLOW_AUTH_OVERRIDE` | Унтраалттай. `1`, `true`, `yes`, `on` үед tool-ийн `allow_auth=true` параметрийг зөвшөөрнө. Зөвхөн desktop эзэмшигч тохируул. |
| `OMNIMCP_STRICT` | Унтраалттай. `1`, `true`, `yes`, `on` үед OmniMCP-ийн сүүлийн үйлдлээс хойш seat шилжсэн бол дараагийн үйлдлийг хориглоно. |
| `OMNIMCP_CONFINE` | Хязгаарлалтгүй. `launched`, `class:foo,bar`, `workspace:3,special:notes` хэлбэрээр оролтын цонхны хамрах хүрээг хязгаарлана. Буруу утга үйлдлийг хориглоно. |
| `OMNIMCP_MARK` | Унтраалттай. `1`, `true`, `yes`, `on` үед өөрийн нээсэн цонхыг `omnimcp-owned` tag хийж, нээх/screenshot хийхэд мэдэгдэл харуулна; border rule зөвхөн best-effort. |
| `OMNIMCP_BACKGROUND` | Default нь automatic: идэвхтэй цонхонд foreground, бусдад background. `1`, `on`, `true`, `yes`, `always` нь background guarantee; `0`, `off`, `false`, `no` нь foreground default. `auto`, `automatic` нь automatic; бусад утга үйлдлийг хориглоно. |
| `OMNIMCP_AGENT_WORKSPACES` | `99-90`. Agent-ийн workspace-уудын эрэмбэлсэн ID/range жагсаалт; `name:x` нэрээр сонгоно. Буруу утгад үйлдэл татгалзана. |
| `OMNIMCP_AGENT_FILL` | `1`. Ачаалал хуваарилахад workspace “дүүрсэн” гэж үзэх agent цонхны босго; эерэг бүхэл тоо байх ёстой. Бүх сонголт дүүрвэл хамгийн цөөн цонхтойг дахин сонгоно. |
| `OMNIMCP_SEAT` | Тодорхойгүй. Хоосон биш үед virtual pointer-д нэрлэсэн Wayland seat шаардана; олдохгүй бол default seat рүү fallback хийхгүй. |
| `OMNIMCP_LAUNCH_ALLOW` | Тодорхойгүй. `launch` command-ийг хязгаарлах одоогийн хэрэглэгчийн эзэмшлийн, group/world бичих эрхгүй regular file-ийг заана. Нэг мөрөнд нэг зөвшөөрсөн executable бич; `#` comment мөр, хоосон мөрийг үл тооно. |
| `OMNIMCP_SCREENSHOT_MODE` | `file`. MCP screenshot-ийг зураг (`image`) эсвэл файл горимоор өгнө; CLI screenshot verb файл горимд буцаана. |
| `OMNIMCP_MAX_IMAGE_BYTES` | `700000`. Зураг буцаахад ашиглах дээд byte хэмжээ. |
| `OMNIMCP_MAX_IMAGE_EDGE` | `1568`. Зургийн хамгийн урт талын дээд пиксел. |
| `OMNIMCP_JOURNAL` | Бичлэг унтраалттай. `1` бол `$XDG_STATE_HOME/omnimcp/journal.ndjson` (эсвэл `~/.local/state/...`), эсвэл зам өгвөл тухайн файлд tool call-уудыг NDJSON-оор бичнэ. |
| `OMNIMCP_JOURNAL_TEXT` | Унтраалттай. `1`, `true`, `yes`, `on` бол бичсэн/copied текстийг бүрнээр нь журналд хадгална. Ингэхэд нууц үг орж болзошгүй. |
| `OMNIMCP_JOURNAL_MAX_BYTES` | `8388608` буюу 8 MiB. Журналын файл тус бүрийн эргүүлэлтийн дээд хэмжээ; `0` эсвэл бага утга эргүүлэлтийг унтраана. |
| `OMNIMCP_KANBAN_FILE` | Тодорхойгүй. Өөрчлөх Kanban Markdown файлын абсолют зам; existing regular `.md` file байх ёстой. |
| `OMNIMCP_BROWSER_COMMAND` | Тодорхойгүй. Browser MCP server-ийн command-ийг JSON string list (`argv`) хэлбэрээр заана. Заагаагүй бол `~/.config/omnimcp/browser.json`, дараа нь PATH дахь `playwright-mcp` ашиглана. |
| `OMNIMCP_STATE_DIR` | `$XDG_STATE_HOME/omnimcp` (эсвэл `~/.local/state/omnimcp`). Worker SQLite DB, artifact хадгалдаг хувийн хавтас. |
| `OMNIMCP_SOCKET` | `$XDG_RUNTIME_DIR/omnimcp-core/worker.sock` (байхгүй үед `/run/user/<uid>/...`). Compact worker-ийн Unix socket зам. |
| `OMNIMCP_BIN` | Codex plugin shim-д л хэрэглэнэ. Бүрэн замаар runtime `OmniMCP` executable заана; өгөөгүй бол shim `PATH`-аас олно. Өөрийг нь заасан эсвэл executable биш бол ажиллахгүй. |

`OMNIMCP_DRYRUN`, `OMNIMCP_READONLY` нь аюулгүй ажиллагааны нэмэлт хязгаар юм.
Эдгээр нь OS sandbox биш: ажиллах үед tool нь нэвтэрсэн хэрэглэгчийн эрхтэй.
`OMNIMCP_BACKGROUND=1` нь зөвхөн Hyprland workspace зохицуулалтын хүрээнд
дэлгэц эзлэхгүй байхыг батална; гаднах программ, өөр session-ийн үйлдлийг
хянахгүй.

## Auth ба admin үйлдэл

Системийн admin үйлдэл native graphical polkit prompt ашиглана. Password-ийг
MCP parameter, stdin эсвэл AI-д өгөхгүй. Auth prompt cancel/timeout болбол дахин
prompt нээхийг worker төлөвөөр хориглоно; хуучин `auth_retry` параметр энэ
хоригийг тайлахгүй. Нэвтэрсэн хэрэглэгч өөрөө шалгасны дараа local owner CLI-аас
`OmniMCP worker auth-reset` ажиллуулж хадгалсан блокийг цэвэрлэнэ. Энэ CLI болон
`pkexec` нь ижил UID-тэй agent shell-ээс дуудагдаж болох тул тусдаа human-consent
эсвэл OS security boundary болохгүй. Нэг worker дотор зэрэгцсэн admin хүсэлтүүд олон prompt
үүсгэхгүй.

`admin.install_helper` нь editable package-ийг root-р ажиллуулахгүй. Тэр зөвхөн
trusted root-owned helper болон policy-г гараар суулгах заавар/`permission_required`
үр дүн өгнө. `config.admin_update` нь symlink-гүй, root эзэмшилтэй helper болон
ancestor зам шаардана; `/etc/omnimcp/allowed-configs.json` нь root хяналттай,
JSON array дотор яг таарах canonical absolute path-уудтай байх ёстой. Helper,
policy, backup-ийн хяналтын замыг уг жагсаалтад оруулахыг хориглоно. Замыг
environment-аар өөрчлөх боломжгүй. Helper-ийг суулгах бодит ажиллагаа энэ
баримтаар хийгдээгүй; системдээ тохируулж суулгах зааврыг тусад нь шалга.

## Хадгалалт ба хязгаар

Compact worker-ийн state болон artifact нь хувийн хавтсанд хадгалагддаг бөгөөд
эмзэг аппын мэдээлэл агуулж болно. Artifact автоматаар устгах хугацаа эсвэл дискний
quota байхгүй. Desktop-ийн хуучин command/action нь бодит нөлөөг үргэлж батлахгүй;
чухал өөрчлөлтийн дараа төлөвийг дахин ажигла. Worker, tool-ийн cancel нь
аль хэдийн хийгдсэн өөрчлөлтийг буцаахгүй. Дэлгэрэнгүй contract, limitation-ийг
[Core баримт](CORE.md)-оос үз.

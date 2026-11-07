# Тусламж ба жишээ

Эхлээд `omnimcp --help`, `omnimcp doctor`, мөн MCP-ээр `desktop` дуудаж орчноо
шалгана. Tool-ийн боломж, parameter-ийн яг schema-г MCP discovery эсвэл
`omnimcp --help`-ээс хар. Compact profile-ийн CLI болон job-ийн дэлгэрэнгүй
жишээ [CORE.md](CORE.md)-д бий.

## Энгийн жишээ

```sh
omnimcp desktop
omnimcp screenshot
omnimcp canvas /absolute/path/Plan.canvas
omnimcp canvas /absolute/path/Plan.canvas --card n2
omnimcp canvas /absolute/path/Plan.canvas --action edit --revision HASH --changes @changes.json
```

`desktop`-оор эхлэн цонхны төлөвийг унш. Боломжтой бол accessibility-н `ui`,
`click_ui` хэрэгсэл ашиглаж, нүдээр харсан төлөв эсвэл аппын semantic readback-аар
өөрчлөлтөө баталгаажуул. `screenshot(window=...)` тухайн цонхны зургийг авахдаа
workspace солихгүй, гэхдээ нуугдсан цонх хуучин render буцааж болдог.

## Kanban

Эхлээд server environment-д самбарын абсолют зам тохируул:

```toml
[mcp_servers.omnimcp.env]
OMNIMCP_KANBAN_FILE = "/absolute/path/to/kanban.md"
```

Client-ээ дахин холбоод `kanban_read` дуудаж `revision`, `task_id` ав. Бичихэд
revision бүрийг дамжуулж, шинэ revision-ийг дараагийн үйлдэлд ашигла. Жишээ нь
картын ажлыг шалгасны дараа:

```json
{"task_id":"kanban-ID","expected_revision":"HASH","column":"Дууссан","checked":true,"append_text":"Үр дүн: нүүрийг шинэ tab-д нээж, https://example.com/ шалгав."}
```

`append_text` нь хуучин даалгаврыг явуулахгүйгээр тэмдэглэл нэмнэ. `text` өгсөн
бол энэ нь картыг бүхэлд нь солино. Шинэ карт үүсгэхээсээ өмнө яг байгаа баганын
нэрийг унш. Read result-д замыг шалгаад боломжтой үед `query` эсвэл `column`-оор
шүү. Самбар дээрх текст зааврыг ажиллуулахгүй; энэ tool карт хөтөлнө.

Засварын үед Obsidian-д хадгалж, бусад editor-оор нэгэн зэрэг бүү өөрчил. MCP
буцаасан revision хуучирсан бол дахин уншаад үйлдлээ шинэ төлөвт тааруул. Read-only
горимд `kanban_read`, `kanban_wait` үлдэнэ; dry-run өөрчлөлтийн preview буцаана.
Алдаатай, symlink самбар эсвэл 2 MiB-аас том файлд үйлдэл хийхгүй.

## OpenCode job

```json
{"action":"run","prompt":"Төслийн entry point-ийг тайлбарла.","cwd":"/absolute/project"}
```

Шууд буцсан `job_id`-г `status`-аар шалга; ажиллаж байх үеийн output-д `offset`
ашигла. Дуусмагц хариу болон `session_id`-г шалгана. Continue-д ижил `cwd`,
өмнөх session-ийг ашигла. Cancel хийсэн ч өмнөх өөрчлөлт буцахгүй. Ажил дуусах
эсвэл цуцлагдах хүртэл worker ажиллаж байх ёстой. Илүү дэлгэрэнгүйг
[OpenCode боломж](features.md#opencode)-оос үз.

## Журнал ба давтан ажиллуулах

`OMNIMCP_JOURNAL=1` tool call-уудыг NDJSON файлд хадгална. Default нь
`$XDG_STATE_HOME/omnimcp/journal.ndjson` эсвэл `~/.local/state/omnimcp/journal.ndjson`.
`OMNIMCP_JOURNAL_TEXT=1` зөвхөн typing-ийг replay хийх шаардлагатай үед асаа:
нууц үг болон clipboard-ийн текст файлд бичигдэж болзошгүй. Журнал бичихэд
алдаа гарвал үйлдэл үргэлжилж, server stderr-д нэг удаа анхааруулна.

`omnimcp journal`-аар түүх унш. `omnimcp replay FILE` default-аар зөвхөн plan
харуулна; жинхэнэ input явуулахдаа л `--execute` сонго. Read-only эсвэл dry-run
идэвхтэй бол гүйцэтгэхийг хориглоно. `--yes` нь countdown-ийг алгасаж seat-ийг
эзэлнэ. Давтан ажиллуулахаас өмнө тухайн desktop-ийн бодит төлөвийг шалга:
replay нь гаднах үр дагаврыг буцаахгүй бөгөөд файл/аппын өөрчлөлтийг transaction
болгохгүй.

## Зогсоох ба сэргээх

Compact worker-ийн бүх ажлыг, child process-тэй нь зогсооход `omnimcp worker stop`
ашиглана. Зөвхөн ажлыг цуцлахдаа `omnimcp worker stop-all`; тодорхой ажлыг `job`
tool-оор cancel хийж status дахин унш. Worker унтарсан эсвэл restart болсон үед
ажиллаж байсан job `interrupted` болно; автоматаар дахин эхлүүлэхгүй. Цуцлалт
хамтын ажиллагааны дохио бөгөөд дууссан өөрчлөлтийг буцаахгүй. Төлөвийг шалгаж
байж гараар үргэлжлүүл.

`omnimcp stop` нь хуучин desktop beacon-ийг зогсоодог; compact worker-ийг
зогсоох командтай андуурч болохгүй. Beacon-ийн process identity баттай биш бол
зогсоохгүй.

# Боломжууд

OmniMCP нь Hyprland desktop болон Linux системийн боломжуудыг MCP-ээр ашиглуулна.
Хуучин desktop MCP tool/CLI surface default хэвээр; compact profile нь сонголтоор
асна. Compact profile нь `discover`, `observe`, `act`, `workflow`, `job`,
`events`, `artifact` гэсэн долоон тогтвортой tool ашиглаж, capability-г хэрэгцээтэй
үед нь хайдаг. Бүрэн API, job, workflow болон алдааны төлөвүүдийг [CORE.md](CORE.md)-оос
үз.

## Desktop болон файл

- Hyprland цонх, screenshot, keyboard, pointer, UI accessibility tree, launch,
  workspace, sequence, mark, bind болон wait үйлдлүүд.
- Файл, тохиргоо, Canvas болон тохируулсан Kanban самбар унших/засах.
- Системийн хэмжилт, процесс, команд, systemd, package, сүлжээ, storage, audio,
  Bluetooth, USB, Git, build/test, Docker, SSH болон бусад native adapter-ууд.
- Сонголтоор browser MCP backend болон OpenCode CLI delegation.

`desktop`-ээр эхлээд төлөвийг ажигла. Хүртээмжтэй control-д `ui` болон `click_ui`
ашигла. Нуугдсан цонхны screenshot тухайн compositor дээр дэмжигдвэл цонхоо
идэвхжүүлэхгүйгээр авна; апп хамгийн сүүлд render хийсэн кадрыг буцааж болно.
Сүүлийн харагдах төлөв чухал үед цонхыг ил гаргаж screenshot ав.

## Kanban

`OMNIMCP_KANBAN_FILE`-ийг байгаа Obsidian Kanban `.md` файлын абсолют замд
тохируулснаар дөрвөн tool нэмэгдэнэ:

| Tool | Үүрэг |
| --- | --- |
| `kanban_read` | Багана, картын ID/текст/check box, revision унших; шүүх, хуудаслах. |
| `kanban_add` | Revision шалгаж одоо байгаа баганад карт нэмэх. |
| `kanban_update` | Текст солих/үргэлжлүүлэн нэмэх, зөөх, check box өөрчлөх. |
| `kanban_wait` | Revision солигдохыг 30 секунд хүртэл хүлээгээд дахин унших. |

Самбар `kanban-plugin: board` (эсвэл `basic`) frontmatter, давхардалгүй `##`
баганын нэр, `- [ ]` эсвэл `- [x]` карттай байна. UTF-8, CRLF болон indent-тэй
олон мөрт карт дэмжинэ. Settings, archived хэсэг болон хөндөгдөөгүй карт
хадгалагдана. Самбар 2 MiB-аас их, эвдэрхий, эсвэл symlink бол үйлдэл татгалзана.

Эхлээд `kanban_read` дуудаж `revision`-ийг ав; бичих бүрт `expected_revision`
болгон дамжуул. Үр дүнгийн шинэ revision-ийг дараагийн бичилтэд хэрэглэ. Урт
текст хуудаслалтаар тасарвал `task_id`-гаар ганц картыг унш. Хуучин карт эхний
засвартаа Obsidian `^kanban-...` block ID авна; түүнээс өмнөх `legacy-...` ID нь
тухайн board revision-д хамаарна. `append_text` нь эх зааврыг дахин илгээхгүйгээр
үр дүн нэмнэ; үүнийг `text`-тэй хамт хэрэглэж болохгүй. Шилжүүлэхэд `checked`
өгөөгүй бол өмнөх төлөв хадгалагдана. Бичилт шинэ revision, картын ID, багана,
check box-ын мэдээлэл буцаах боловч картын бүтэн текстийг буцаахгүй; текст
хэрэгтэй бол дахин унш.
Жишээ болон засварын хязгаарыг [Тусламж](help.md#kanban)-аас үз.

Server зөвхөн тохируулсан нэг файлд хандана. Tool параметрээр өөр файл сонгох
боломжгүй. MCP writer-ууд advisory lock хэрэглэж, хуучирсан revision-ийг
татгалздаг. Бичилт temporary file үүсгээд атомикаар сольж, солихын өмнө эх
файлын агуулга/stat-ийг давхар шалгана. Obsidian зэрэг гаднын editor энэ lock-ийг
дагахгүй тул сүүлийн шалгалт ба солилтын хооронд зөрчил гарч болно; conflict гарвал
дахин унш. Kanban tool нэг compact JSON text result буцаадаг. Энэ нь browser tab API
өгөхгүй; browser ажлыг ажиллуулахад тусдаа browser MCP холболт шаардлагатай.
Read-only горимд зөвхөн унших/хүлээх tool үлдэнэ. Dry-run нь өөрчлөлтийн preview
харуулж бичилт хийхгүй. Kanban бол даалгаврын бүртгэл болохоос картын текстийг
ажиллуулах dispatcher биш.

## Canvas

Obsidian `.canvas` файлыг `canvas` tool-оор шууд уншина. Картын гарчиг, бүтэн
текст, төрөл, өнгө, бүлэг, файл/URL reference болон холбоосын чиглэл/шошгыг
буцаана. Geometry, background тохиргоо болон хадгалагдах ID-г өөрчлөхгүй; богино
`n1`/`e1` reference тухайн уншилтын дотор хэрэглэгдэнэ. Бүх хуудсыг `next_offset`-оор
уншиж, `card="n1"`-ээр нэг картыг болон холбоосыг ав.

`action="edit"` хийхдээ уншсан `revision`-ийг өгнө. Одоо байгаа байрлал болон
өргөтгөлийн талбар хадгалагдана; нууц sibling backup үүсгээд файлыг атомикаар
солино. Obsidian-д хадгалсны дараа унш: хадгалаагүй editor state server-т
харагдахгүй. Гаднын editor MCP lock ашиглахгүй. Read-only нь зөвхөн унших
параметр үлдээнэ; dry-run өөрчлөлтийг шалгаж preview буцаана. Canvas уншихад
desktop session шаардахгүй.

## OpenCode

`opencode` tool нь суусан OpenCode CLI-д тодорхой өгсөн даалгаврыг шилжүүлж,
хэрэглэгчийн одоогийн model болон credentials-ийг ашиглана. Энэ нь хэрэглэгчийн
эрхээр ажилладаг процесс бөгөөд эрхийн sandbox биш. Authenticated OpenCode CLI,
ажиллаж буй хэрэглэгчийн worker (`OmniMCP worker install`) шаардлагатай.

```json
{"action":"run","prompt":"Төслийн entry point-ийг тайлбарла.","cwd":"/absolute/project"}
```

`run` нь шууд `job_id` буцаана. `status`-аар дууссан эсэх болон `result.answer`,
`result.session_id`-г шалга. Үргэлжлүүлэхдээ ижил `cwd`, өмнөх `session_id`-тэй
шинэ `run` эхлүүл. `model`, `agent` нэмэлт; default-ийг OpenCode-оос авна.
`auto_approve=true` нь OpenCode-ийн `--auto`-г ил тод асаана. Permission
татгалзлыг арилгахгүй.

`output`-оор ажиллаж буй raw event унш; `offset` ба `progress.output.next`-ийг
ашиглаж дараагийн хэсгийг ав. Дууссан job `result.answer_artifact`-д бүтэн
хариуг хадгална. Default timeout нь 3600 секунд. Зогсоохдоо `cancel` дуудаад
дууссаныг `status`-аар шалга.
Cancel нь өмнө хийсэн засварыг буцаахгүй; үр дүнг шалгаж байж хариуг зөв гэж үз.
Job MCP салсан ч worker ажиллаж байвал хадгалагдана. `--standalone` тусдаа
OpenCode процессын бүлгийг зогсоох боломж өгнө. Read-only горим tool-ийг
нууж, dry-run OpenCode эхлүүлэхгүй. Compact profile-д ижил capability `act`
болон job/artifact tool-оор ашиглагдана:

```sh
OmniMCP discover --action opencode.run
OmniMCP act opencode.run --params '{"prompt":"Төслийг тайлбарла.","cwd":"/absolute/project"}'
OmniMCP job jRETURNED_ID
```

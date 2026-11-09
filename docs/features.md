# Боломжууд

OmniMCP нь Hyprland desktop болон Linux системийн боломжуудыг MCP-ээр ашиглуулна.
Desktop MCP tool/CLI surface default хэвээр; compact profile нь сонголтоор
асна. Compact profile нь `discover`, `observe`, `act`, `workflow`, `job`,
`events`, `artifact` гэсэн долоон тогтвортой tool ашиглаж, capability-г хэрэгцээтэй
үед нь хайдаг. Бүрэн API, job, workflow болон алдааны төлөвүүдийг [CORE.md](CORE.md)-оос
үз.

## Desktop болон файл

- Hyprland цонх, screenshot, keyboard, pointer, UI accessibility tree, launch,
  workspace, sequence, mark, bind болон wait үйлдлүүд.
- Файл, тохиргоо унших/засах.
- Системийн хэмжилт, процесс, команд, systemd, package, сүлжээ, storage, audio,
  Bluetooth, USB, Git, build/test, Docker, SSH болон бусад native adapter-ууд.
- Сонголтоор browser MCP backend болон OpenCode CLI delegation.

`desktop`-ээр эхлээд төлөвийг ажигла. Хүртээмжтэй control-д `ui` болон `click_ui`
ашигла. Нуугдсан цонхны screenshot тухайн compositor дээр дэмжигдвэл цонхоо
идэвхжүүлэхгүйгээр авна; апп хамгийн сүүлд render хийсэн кадрыг буцааж болно.
Сүүлийн харагдах төлөв чухал үед цонхыг ил гаргаж screenshot ав.

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

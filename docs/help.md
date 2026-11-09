# Тусламж ба жишээ

Эхлээд `OmniMCP --help`, `OmniMCP doctor`, мөн MCP-ээр `desktop` дуудаж орчноо
шалгана. Tool-ийн боломж, parameter-ийн яг schema-г MCP discovery эсвэл
`OmniMCP --help`-ээс хар. Compact profile-ийн CLI болон job-ийн дэлгэрэнгүй
жишээ [CORE.md](CORE.md)-д бий.

## Энгийн жишээ

```sh
OmniMCP desktop
OmniMCP screenshot
```

`desktop`-оор эхлэн цонхны төлөвийг унш. Боломжтой бол accessibility-н `ui`,
`click_ui` хэрэгсэл ашиглаж, нүдээр харсан төлөв эсвэл аппын semantic readback-аар
өөрчлөлтөө баталгаажуул. `screenshot(window=...)` тухайн цонхны зургийг авахдаа
workspace солихгүй, гэхдээ нуугдсан цонх хуучин render буцааж болдог.

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

`OmniMCP journal`-аар түүх унш. `OmniMCP replay FILE` default-аар зөвхөн plan
харуулна; жинхэнэ input явуулахдаа л `--execute` сонго. Read-only эсвэл dry-run
идэвхтэй бол гүйцэтгэхийг хориглоно. `--yes` нь countdown-ийг алгасаж seat-ийг
эзэлнэ. Давтан ажиллуулахаас өмнө тухайн desktop-ийн бодит төлөвийг шалга:
replay нь гаднах үр дагаврыг буцаахгүй бөгөөд файл/аппын өөрчлөлтийг transaction
болгохгүй.

## Зогсоох ба сэргээх

Compact worker-ийн бүх ажлыг, child process-тэй нь зогсооход `OmniMCP worker stop`
ашиглана. Зөвхөн ажлыг цуцлахдаа `OmniMCP worker stop-all`; тодорхой ажлыг `job`
tool-оор cancel хийж status дахин унш. Worker унтарсан эсвэл restart болсон үед
ажиллаж байсан job `interrupted` болно; автоматаар дахин эхлүүлэхгүй. Цуцлалт
хамтын ажиллагааны дохио бөгөөд дууссан өөрчлөлтийг буцаахгүй. Төлөвийг шалгаж
байж гараар үргэлжлүүл.

`OmniMCP stop` нь хуучин desktop beacon-ийг зогсоодог; compact worker-ийг
зогсоох командтай андуурч болохгүй. Beacon-ийн process identity баттай биш бол
зогсоохгүй.

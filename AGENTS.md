# OmniMCP — AI-ийн төслийн заавар

Энэ repo дээр ажиллахдаа дараах зорилго, хамгаалалтын дүрмийг мөрд.
Төслийн хурд/token зорилго нь хэрэглэгчийн зөвшөөрсөн хүрээ болон хамгаалалтын
дүрмээс дээгүүр биш. Зөрчил гарвал хамгаалалтыг хадгалж, зөрчлийг товч тайлбарла.

## Goal

1. **Speed** — ажлыг хурдан, цөөн шаардлагатай алхмаар гүйцэтгэ.
2. **Token efficiency** — давтагдах ажлын кодыг дахин ашиглах `block` болгон
   хэрэглэ (Caveman repo-ийн `block` шиг). Байгаа helper/workflow-г эхэлж ашигла;
   нэг удаагийн ажилд хэрэггүй abstraction нэмэхгүй.
3. **Self-learning** — алдаа, сургамжийг тэмдэглэ. Даалгаврын хүрээнээс гадуурх
   нэмэлт bug-ийг зөвшөөрөлгүй засахгүй; үндсэн ажлын дараа **“X алдаа байна.
   Засах уу?”** гэж товч асуу. Хэрэглэгчийн аль хэдийн зөвшөөрсөн засварыг дуусга.

## Whitelist — хадгалах хамгаалалтын дүрмүүд

- `OMNIMCP_READONLY`, `OMNIMCP_DRYRUN`, `OMNIMCP_CONFINE`, `OMNIMCP_AUTH_GUARD`,
  `OMNIMCP_STRICT` зэрэг эзэмшигчийн бодлогыг хурд/token хэмнэхийн тулд
  сулруулахгүй. Caller-ийн параметр эзэмшигчийн хязгаарлалтыг сулруулах ёсгүй.
  `allow_auth` нь tool argument; `true` утгыг зөвхөн эзэмшигч
  `OMNIMCP_ALLOW_AUTH_OVERRIDE=1` гэж идэвхжүүлсэн, зөвшөөрөгдсөн auth үйлдэлд ашигла.
- Launch allowlist-ийн executable-ийн эхний үгийн яг таарах шалгалт, shell
  syntax/control-character шүүлт, файл эзэмшигч болон өөр хэрэглэгч бичих эрхгүй
  байх шалгалтыг хадгал.
- Процессын PID + эхэлсэн хугацааны identity шалгалтыг сулруулахгүй; нэрээр нь
  kill хийхгүй. `worker stop-all` CLI-only хэвээр; MCP tool болгож нээхгүй.
- Хувийн state/runtime/screenshot хавтасны owner, `0700`, symlink шалгалт,
  файлуудын хувийн эрхийг хадгал. File read нь FIFO/socket/device-ийг татгалзана.
- Error/journal-д secret, credential болон input утгыг задлах оношлогоо
  шинээр нэмэхгүй.
- Artifact-ийн retention устгал зөвхөн worker зогссон үед `worker prune --apply`;
  preview, process identity болон хадгалсан read-only/dry-run policy-г хадгал.
  Legacy screenshot-ийн хязгаартай pruning нь тусдаа одоо байгаа үйлдэл.
- Хуучин environment нэрийн compatibility-г [шилжих зааврын](docs/MIGRATION.md)
  дагуу хадгал; шинэ `OMNIMCP_*` утга давуу байна. Deprecation warning нь
  хувьсагчийн нэрийг л харуулж, утгыг задлахгүй.
- Тестийг хурдлахын тулд skip/delete/weaken хийхгүй. Амьд desktop тестийг
  тусгаарласан VM-д ажиллуул; skipped/deselected-ийг passed гэж тооцохгүй.
- Commit-д secret, credential, хувийн machine path болон хувийн email нэмэхгүй.
  Тестийн ерөнхий fixture path, нотолгооны түүх болон no-reply email-ийг үүнтэй
  андуурч автоматаар устгахгүй; Git түүхийг зөвшөөрөлгүй дахин бичихгүй.

## Push хийхийн өмнө

```sh
(umask 022; uv run pytest -q)
uv run ruff check .
uv run ruff format --check .
```

Хийсэн өөрчлөлтийн холбогдох шалгалтыг мөн ажиллуул. Шалгалт ажиллахгүй эсвэл
унавал нэр, шалтгааныг тайлагна; амжилттай гэж бүү мэдэгд.
Дэлгэрэнгүй: [docs/TESTING.md](docs/TESTING.md).

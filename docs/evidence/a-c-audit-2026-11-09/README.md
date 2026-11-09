# A/C аудитын сонгосон нотолгоо

Аудитын commit: `eaabe434519a291dd5f8108014fe7186570e5418`.
Эдгээр нь synthetic fixture болон тусгаарласан VM-ийн өгөгдөл. Production код
өөрчлөгдөөгүй. [Эцсийн тайлан](../../audits/2026-11-09-a-c-audit.md)-г эхэлж унш.

`*-report.md` нь auditor бүрийн анхны тайлан. Тэдгээрийн candidate болон эхний
дүгнэлт бүрийг батлагдсан алдаа гэж үзэхгүй; эцсийн тайлан, independent review
нь adjudication-ийг агуулна. Constructor FD leak гэсэн анхны саналыг няцаасан.

## Дахин гаргах

Repo-ийн dev environment-ийг суулгаад, Linux дээр:

```sh
uv run python docs/evidence/a-c-audit-2026-11-09/repros/independent.py.txt
uv run python docs/evidence/a-c-audit-2026-11-09/repros/stop-fifo.py.txt
uv run python docs/evidence/a-c-audit-2026-11-09/repros/grim-formats.py.txt
```

Эдгээр нь өөрийн temp файл/socket болон mocked signal ашиглана. Хүний desktop
эсвэл ambient process руу input/signal явуулахгүй. FD тооллого `/proc` шаарддаг.

Audit-only red case-уудыг production suite-д нэмээгүй. Түр хавтсанд хуулж ажиллуул:

```sh
audit_tmp=$(mktemp -d)
cp docs/evidence/a-c-audit-2026-11-09/repros/test_audit_invariants.py.txt "$audit_tmp/test_audit_invariants.py"
uv run pytest -q --confcutdir="$audit_tmp" "$audit_tmp/test_audit_invariants.py"
```

Audited commit дээр **9 failed** нь зориудын invariant counterexample; одоо байгаа
production suite-ийн төлөвтэй андуурахгүй. `audit-invariants-red.log.gz`-д нэр бүр бий.

Property probe-д Hypothesis, mutation campaign-д Mutmut тусдаа audit tool environment
шаардсан; project dependency-г өөрчлөөгүй. `property-results.json` болон
`mutation-results.txt` нь гүйцэтгэсэн бодит хүрээ/үр дүнг агуулна.
Mutation-ийг original checkout дээр ажиллуулахгүй. Audited commit-ийн тусдаа
copy-д `mutmut-config.toml.txt`-ийг pyproject-д нэмж дараах selection ашигласан:

```sh
mutmut run --max-children 2 '*guard_allow_auth_override*' '*shutdown*' '*redact__mutmut*'
```

Tool хувилбарууд `tool-versions.json`, Semgrep-ийн хязгаартай таван local rule
`semgrep-rules.yml`-д бий. Official registry-ийн бүх Semgrep rule ажиллуулсан гэж
үзэхгүй.

## Хадгалсан ба хасаад үлдээсэн зүйл

- `vm/`: exact wheel/source hashes, package versions, live failure log,
  acceptance JSON/PNG, device growth болон teardown status.
- `coverage-summary.json`: host line/branch хэмжилт; VM coverage ороогүй.
- `bandit.json`, `semgrep.json`, `mypy.log`, `dependency-audit.json`: raw scanner
  үр дүн; hit бүр батлагдсан finding биш.
- Root images, source tar, tool venv/cache, build network logs болон бүх түр
  pytest файлыг Git-д оруулаагүй. Бүх original artifact аудитын scratch-д хадгалагдсан.
- `sha256.json` нь curated файл бүрийн checksum. Manifest өөрийгөө хэшлэхгүй.

VM-д шинэ source/test patch хийгээгүй. Official grim дээр JPEG алдааг хадгалсан;
JPEG-enabled passing run байхгүй. Teardown **139** хэвээр, clean lifecycle гэж
дүгнээгүй. Raw evidence нь өмнөх аудитын файлуудыг дарж бичээгүй.

Pytest болон package-version raw текстүүдийг whitespace өөрчлөхгүйгээр `.gz`
хэлбэрээр хадгалсан. `gzip -dc FILE.gz`-ээр уншина; raw тайлангийн original
filename нь scratch artifact-ийн нэр, curated хувилбар нь шахсан нэртэй байна.

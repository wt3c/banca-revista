# Banca Revista

Ferramenta em Python para diagnosticar, normalizar e converter arquivos de quadrinhos usados pelo Calibre,
principalmente `CBR` e `CBZ`.

O primeiro caso de teste será `SIDOOH - Volume 01 [Packs de HQs].cbr`. Os arquivos de entrada devem ser tratados como
somente leitura; resultados só serão publicados em `~/banca` depois que a conversão piloto passar por todas as
validações.

## Desenvolvimento

Requisitos:

- Python 3.12 ou superior;
- [uv](https://docs.astral.sh/uv/).
- `unrar` e `rar` para ler e criar metadados em CBR;
- `poppler-tools` para extrair ou renderizar páginas de PDF;
- Tesseract com os idiomas `eng` e `por`, além do ImageMagick, para analisar texto das páginas.

Prepare o ambiente e execute as verificações:

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

O arquivo `uv.lock` faz parte do projeto e deve ser versionado para manter o ambiente reproduzível.

## Uso

Inspecione um `CBR` sem alterar o arquivo:

```bash
uv run banca-revista inspect "/caminho/arquivo.cbr"
```

Converta um `CBR` em um novo `CBZ`:

```bash
uv run banca-revista convert "/caminho/arquivo.cbr" "/caminho/resultado.cbz"
```

A conversão exige o executável `unrar`, testa a integridade da origem, coloca somente as imagens na raiz do `CBZ`,
preserva seus bytes e valida novamente conteúdo, ordem e CRC antes de publicar a saída. Um arquivo existente nunca é
sobrescrito.

Para manter arquivos no formato `CBR` e permitir que o Calibre do openSUSE capture a capa automaticamente, consulte a
[instalação do plugin local](docs/calibre-capas-cbr-cbz.md#plugin-para-o-calibre-do-opensuse).

Analise as duas primeiras páginas e gere um relatório JSON com valores, evidências e confiança:

```bash
uv run banca-revista ocr "/caminho/arquivo.cbr"
```

Acrescente `--lookup-isbn` para consultar o catálogo oficial da Biblioteca Nacional do Japão. Somente o ISBN é enviado;
as imagens permanecem locais.

Crie uma nova cópia CBR com capa automática e metadados `ComicBookInfo` sem alterar a origem:

```bash
uv run banca-revista metadata origem.cbr resultado.cbr \
  --title "SIDOOH - Volume 01" \
  --author "Tsutomu Takahashi" \
  --series "SIDOOH" \
  --volume 1 \
  --isbn 9784088768120
```

O fluxo completo pode ser executado em um único comando. Autor e editora aceitam substituição quando a grafia ou a
edição visual diferirem do registro associado ao ISBN:

```bash
uv run banca-revista enrich origem.cbr resultado.cbr \
  --author "Tsutomu Takahashi" \
  --publisher "Panini Comics" \
  --tag "Mangá"
```

Converta individualmente um PDF ou ZIP para CBR:

```bash
uv run banca-revista to-cbr origem.pdf resultado.cbr
uv run banca-revista to-cbr colecao.zip resultado.cbr
```

O modo automático preserva JPEGs de PDFs com exatamente uma imagem por página. Outros PDFs são renderizados a 200 DPI.
ZIPs de imagens são recompactados; ZIPs contendo vários CBRs são unidos na ordem natural das edições e páginas.

Planeje o processamento completo da pasta padrão do Telegram sem criar arquivos:

```bash
uv run banca-revista batch-to-cbr
```

Na execução, cada arquivo PDF, ZIP ou RAR reconhecido pelo conteúdo passa pela conversão para RAR 5, achatamento das
páginas na raiz, OCR das duas primeiras imagens, consulta de ISBN e gravação de metadados. Acrescente `--execute`
somente depois de revisar o JSON:

```bash
uv run banca-revista batch-to-cbr --execute
```

A execução continua após falhas, não sobrescreve saídas, preserva os originais e salva `conversion-report.json` no
diretório `~/banca`. O relatório registra os metadados efetivamente gravados e avisa quando não encontra ISBN nas duas
primeiras imagens.

Até 10 pipelines completos são executados em processos independentes por padrão. As etapas de um mesmo arquivo são
sequenciais porque dependem do resultado anterior, enquanto arquivos diferentes avançam em paralelo. Ajuste o limite
explicitamente quando necessário:

```bash
uv run banca-revista batch-to-cbr origem ~/banca --execute --workers 10
```

Para reconstruir saídas existentes, use `--replace-existing`. Cada arquivo anterior permanece disponível até a nova
cópia sem senha passar por todas as validações e substituí-lo atomicamente.

Durante a execução, a interface colorida mostra o total de arquivos, barras por fase, percentual, contadores, tempo
decorrido, quantidade de workers ativos, fila restante e uma linha por arquivo em andamento com sua etapa atual. O
painel final resume processados, ignorados, falhas, avisos e ISBNs encontrados. Para integrar o comando a scripts sem
códigos de cor ou elementos visuais, solicite a saída estruturada:

```bash
uv run banca-revista batch-to-cbr --json
uv run banca-revista batch-to-cbr --execute --json
```

## Documentação

- [Diagnóstico de capas ausentes em CBR e CBZ](docs/calibre-capas-cbr-cbz.md)
- [Conversão de PDF e ZIP para CBR](docs/conversao-pdf-zip-cbr.md)

## Estado atual

A inspeção, a conversão segura e o enriquecimento por OCR/metadados estão implementados. O piloto validado também foi
recompactado como RAR/CBR verdadeiro e salvo em `pilotos/`, uma pasta local ignorada pelo Git. O comando em lote
converte PDF/ZIP/CBZ, processa os CBRs e publica cópias validadas em `~/banca`.

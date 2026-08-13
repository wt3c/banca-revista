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

Acrescente `--lookup-isbn` para consultar o catálogo oficial da Biblioteca Nacional do Japão. Somente o ISBN é
enviado; as imagens permanecem locais.

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

## Documentação

- [Diagnóstico de capas ausentes em CBR e CBZ](docs/calibre-capas-cbr-cbz.md)

## Estado atual

A inspeção e a conversão segura de um único `CBR` estão implementadas. O piloto validado também foi recompactado como
RAR/CBR verdadeiro e salvo em `pilotos/`, uma pasta local ignorada pelo Git. O processamento em lote e a publicação em
`~/banca` permanecem para uma próxima etapa.

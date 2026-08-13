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

Prepare o ambiente e execute as verificações:

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

O arquivo `uv.lock` faz parte do projeto e deve ser versionado para manter o ambiente reproduzível.

## Documentação

- [Diagnóstico de capas ausentes em CBR e CBZ](docs/calibre-capas-cbr-cbz.md)

## Estado atual

Esta etapa contém somente a configuração do projeto. A inspeção do arquivo piloto, a implementação da conversão e o
processamento em lote serão feitos nas próximas etapas.

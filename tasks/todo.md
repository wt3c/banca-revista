# Tarefas

## Ativa — extrair contêineres ZIP/RAR de quadrinhos antes da conversão (2026-10-21)

Origem: `Rainha dos Vampiros.zip` (7 `.cbz`) e `Wolverine.O.Melhor.Que.Há.zip` (1 `.pdf` + 11 `.cbr`) falharam com
"conteúdo ZIP ambíguo", porque `classify_zip_entries` só aceita imagens ou `.cbr`.

Regra pedida: antes de converter um ZIP/RAR, analisar o conteúdo.

- Só imagens → processar normalmente.
- `.cbz`, `.cbr` ou `.pdf` → extrair para o mesmo diretório do arquivo e converter cada um pelo fluxo normal.

### Etapas

- [x] Testes (TDD) para classificação de contêiner ZIP e RAR (`.cbz`/`.cbr`/`.pdf`), mistura ambígua e entradas inseguras
- [x] Testes para extração: atômica, sem sobrescrever, idempotente com conteúdo idêntico, falha com conteúdo diferente
- [x] Testes do lote: simulação não extrai; execução real extrai e converte os itens extraídos; contêiner fica no relatório
- [x] Implementar `container.py` (inspeção sem escrita + extração separada)
- [x] Integrar em `plan_batch`/`run_batch`; `convert_to_cbr` recusa contêiner com mensagem clara
- [x] Atualizar `docs/conversao-pdf-zip-cbr.md` e `AGENTS.md` (exceção de escrita na origem)
- [x] `uv run pytest`, `ruff check`, `ruff format --check`, `git diff --check -- '*.md'`
- [x] Revisão: Codex + revisor sênior
- [x] Simulação na origem real (2 contêineres planejados, nada escrito)
- [x] Validação em cópias isoladas (19/19 convertidos; reexecução idempotente; originais com SHA-256 intacto)
- [x] Execução na origem real + publicação em `~/banca` (2 extraídos, 19 processados, originais intactos)

## Ativa — enviar originais à Lixeira após publicação bem-sucedida (2026-10-21)

Pedido: ao publicar em `~/banca` com sucesso, remover o original; na origem ficam só os que tiveram problema.
Decisões aprovadas: Lixeira (freedesktop.org), não exclusão definitiva; só itens `processed` nesta execução
(`skipped` fica). Contêiner sai só quando todos os quadrinhos extraídos dele saíram.

- [x] Testes (TDD) de `trash.py`: move com `.trashinfo`, não sobrescreve nome existente na Lixeira
- [x] Testes do lote: sem opção nada sai; `processed` sai; `failed`/`skipped` ficam; regra do contêiner; simulação
- [x] Implementar `trash.py` (stdlib, `os.link` + `unlink`, mesma partição) e etapa final em `run_batch`
- [x] CLI `--remove-originals`, relatório (`source_removed`) e resumo na tela
- [x] Atualizar `AGENTS.md` e `docs/conversao-pdf-zip-cbr.md`
- [x] `pytest`, `ruff`, validação em cópias (10 na Lixeira, 6 PDFs com senha mantidos); simulação real
- [x] Execução real com `--remove-originals`, 10 workers (10 publicados e na Lixeira; 6 PDFs com senha mantidos)

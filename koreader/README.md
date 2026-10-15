# Leitor KOReader — Panels+ adaptado

`panelsplus/` é uma cópia vendorizada do plugin [Panels+](https://github.com/KristanLaimon/PanelsPlus)
(licença MIT, ver `panelsplus/LICENSE`), tag `v1.4.0`, com três mudanças nossas:

- duplo clique sobre um quadro abre a visão quadro a quadro (`src/native_panel_zoom.lua`, `main.lua`);
- zoom fixo: todos os quadros usam o zoom que ajusta a largura da página à janela (`src/_panelviewer.lua`);
- leitura da esquerda para a direita (`comic`) por padrão (`src/_settings.lua`).

O instalador (`uv run banca-revista instalar-leitor`) não copia esta pasta: ele baixa o release oficial v1.4.0,
confere o SHA-256 e aplica `src/banca_revista/dados/panelsplus-v1.4.0.patch`. O release difere levemente da tag
(nome interno `panelsplus` e migração de configurações antigas), por isso o patch é aplicado sobre ele em vez de
instalar esta árvore. O teste `test_bundled_patch_matches_vendored_plugin_source` garante que o patch é exatamente
a diferença entre a v1.4.0 e esta pasta.

## O que ficou de fora da cópia

- `tests/dataset-mangas/` e os specs que dependem dele (`dataset_benchmark`, `new_dataset_benchmark`,
  `textbasedformats_dataset`, `dataset_support`): contêm páginas de mangá reais, que este repositório não versiona.
  As entradas correspondentes foram removidas de `tests/run_tests.lua`.
- `.github/`, `docs/releases/`, scripts de build/dispositivo, testes em Python e o `CLAUDE.md` do autor.

## Testes do plugin

```bash
cd koreader/panelsplus
luajit tests/run_tests.lua
```

## Alterar o plugin

1. Editar o código em `panelsplus/` e os testes em `panelsplus/tests/spec/`, com a suíte Lua passando.
2. Regenerar o patch a partir de um clone do upstream na tag `v1.4.0`, com esta árvore copiada por cima:

   ```bash
   git diff --src-prefix=a/ --dst-prefix=b/ v1.4.0 -- main.lua src/ \
     > /caminho/banca-revista/src/banca_revista/dados/panelsplus-v1.4.0.patch
   ```

3. Rodar `uv run pytest` e, com rede, `BANCA_TESTE_REDE=1 uv run pytest tests/test_leitor.py`.

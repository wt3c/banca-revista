# AGENTS.md — instruções do projeto Banca Revista

## Objetivo

- Desenvolver uma ferramenta Python para diagnosticar, normalizar e converter quadrinhos para formatos compatíveis
  com o Calibre, com foco inicial em `CBR` e `CBZ`.
- Consulte `docs/calibre-capas-cbr-cbz.md` antes de alterar regras de normalização ou critérios de validação.
- Use o código oficial do Calibre em <https://github.com/kovidgoyal/calibre> como referência para compatibilidade; não
  copie componentes nem assuma comportamento sem conferir a implementação e a licença atuais.

## Ambiente e comandos

- Gerencie Python e dependências exclusivamente com `uv`; mantenha `uv.lock` versionado.
- Use Python 3.12 ou superior e `pathlib.Path` para caminhos.
- Instale o ambiente com `uv sync --dev`.
- Execute testes com `uv run pytest`.
- Execute qualidade com `uv run ruff check .` e `uv run ruff format --check .`.
- Antes de concluir uma mudança, rode as verificações proporcionais ao risco e informe qualquer validação omitida.

## Estrutura e implementação

- Código de produção fica em `src/banca_revista/` e testes em `tests/`.
- Separe inspeção, planejamento da conversão, escrita do resultado e publicação. Funções de inspeção não devem alterar
  arquivos.
- Prefira biblioteca padrão. Adicione dependências somente quando reduzirem risco ou complexidade de forma material.
- Detecte o formato real pelo conteúdo do arquivo, não apenas pela extensão.
- Preserve nomes Unicode e ordene páginas de forma natural e determinística.
- Rejeite arquivos protegidos por senha, corrompidos ou com entradas inseguras; nunca extraia caminhos absolutos ou com
  travessia por `..`.

## Dados e segurança operacional

- A origem inicial é `/home/boladuz/Downloads/Telegram Desktop` e deve ser tratada como somente leitura.
- O arquivo piloto é `SIDOOH - Volume 01 [Packs de HQs].cbr`.
- Nunca versione quadrinhos, páginas extraídas, arquivos temporários grandes ou dados pessoais do acervo.
- Trabalhe em diretório temporário isolado e limpe-o apenas depois de fechar todos os arquivos.
- Não sobrescreva, renomeie, mova nem remova originais.
- Só escreva resultados em `~/banca` após pedido explícito e após validar o arquivo piloto.
- Conversão em lote exige modo de simulação, relatório por arquivo e continuação segura após falha.

## Critérios mínimos para uma conversão

- O arquivo de saída é um ZIP válido com extensão `.cbz`.
- As páginas estão na raiz do arquivo, legíveis e em ordem determinística.
- A quantidade e o conteúdo das páginas correspondem à origem; diferenças intencionais devem ser relatadas.
- A primeira página é reconhecida como capa pelo Calibre.
- A saída é criada de forma atômica e não substitui um arquivo existente sem autorização explícita.
- O original permanece intacto até a validação completa e a decisão posterior do usuário.

## Git e documentação

- Preserve alterações não relacionadas e não faça commit, push ou operações remotas sem pedido explícito.
- Documente contratos, riscos e decisões duráveis sem repetir o código.
- Em Markdown novo ou alterado, use linhas de até 120 colunas quando possível e valide com
  `git diff --check -- '*.md'`.

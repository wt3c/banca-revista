# Conversão de PDF e ZIP para CBR

## Objetivo

A ferramenta converte PDFs e ZIPs em RAR 5 com extensão `.cbr`, sem alterar os arquivos originais; só a opção
`--remove-originals` os retira da origem, enviando-os à Lixeira. A origem inicial desta etapa é:

```text
/home/boladuz/Downloads/Telegram Desktop
```

As saídas convertidas nunca são criadas nessa pasta. A única escrita permitida nela é a extração de contêineres,
descrita abaixo. Um destino existente não é sobrescrito.

## Conversão individual

Use o mesmo comando para PDF ou ZIP; o formato real é detectado pelo cabeçalho:

```bash
uv run banca-revista to-cbr "/caminho/origem.pdf" "/caminho/resultado.cbr"
uv run banca-revista to-cbr "/caminho/colecao.zip" "/caminho/resultado.cbr"
```

Ao concluir, o comando informa formato detectado, estratégia, quantidade de páginas e nome da capa.

## Estratégias para PDF

No modo `auto`, a ferramenta usa extração sem perdas quando o PDF contém exatamente uma imagem JPEG em cada página.
Os bytes dos JPEGs são preservados, evitando uma nova compressão.

PDFs com texto, vetores, várias imagens por página ou formatos internos diferentes são renderizados com Poppler. O
padrão é JPEG com qualidade 92 a 200 DPI. As opções podem forçar uma estratégia:

```bash
uv run banca-revista to-cbr origem.pdf resultado.cbr --pdf-mode lossless
uv run banca-revista to-cbr origem.pdf resultado.cbr --pdf-mode render --dpi 300
```

O modo `lossless` falha em vez de degradar silenciosamente quando a estrutura não é compatível. PDFs protegidos por
senha são rejeitados.

## Estratégias para ZIP

A estrutura é detectada automaticamente:

- ZIP de imagens: as imagens são ordenadas naturalmente e copiadas sem alteração;
- ZIP ou RAR com `.cbr`, `.cbz` ou `.pdf`: é um contêiner de quadrinhos (ver abaixo); o `to-cbr` o recusa e indica
  o comando `batch`;
- conteúdo misto ou desconhecido: a conversão é rejeitada como ambígua.

As páginas finais recebem nomes sequenciais como `000001.jpg`. Isso elimina colisões entre edições sem modificar os
bytes das imagens.

## Contêineres de quadrinhos

Antes de converter um ZIP ou RAR, o conteúdo é analisado. Se houver imagens, o arquivo é tratado como um quadrinho
normal. Se houver `.cbr`, `.cbz` ou `.pdf`, ele é um contêiner: no lote, cada quadrinho é extraído para a mesma pasta
do contêiner e depois convertido individualmente, gerando um `.cbr` por edição na biblioteca.

Regras da extração:

- a simulação não extrai nada; apenas lista o que seria extraído na fase `extract`;
- o contêiner original nunca é alterado; só sai da origem com `--remove-originals` (veja abaixo);
- cada arquivo é gravado em temporário oculto (`.banca-*.tmp`), validado pelo cabeçalho e publicado sem sobrescrita;
- um arquivo homônimo com o mesmo SHA-256 é reaproveitado, o que torna a reexecução idempotente; com conteúdo
  diferente, o contêiner falha e o lote continua;
- quadrinhos que produziriam a mesma saída (`X.pdf` e `X.cbz`, ou um `X.pdf` já presente na pasta), caminhos
  inseguros ou entradas com senha fazem só aquele contêiner falhar, antes de qualquer escrita;
- havendo imagens, o arquivo é um quadrinho comum mesmo que traga um `.pdf`/`.cbr` extra: o ZIP continua rejeitado
  como ambíguo e o RAR converte apenas as imagens, como antes;
- temporários `.banca-*` deixados por uma interrupção são ignorados pelo planejamento;
- contêineres extraídos que contenham outros contêineres são extraídos na mesma execução;
- se a extração falhar no meio, os arquivos já publicados permanecem, pois são cópias íntegras do conteúdo.

## Processamento em lote

O modo em lote inspeciona, pelo conteúdo, os arquivos no primeiro nível da pasta e executa para cada entrada suportada:

1. converte PDF, ZIP ou RAR para um CBR verdadeiro em RAR 5;
2. coloca as páginas diretamente na raiz e valida ordem, quantidade e conteúdo;
3. aplica OCR nas duas primeiras imagens e consulta o catálogo NDL quando encontra um ISBN válido;
4. grava os metadados encontrados e publica a cópia validada em `~/banca`.

Sem `--execute`, ele apenas imprime o plano JSON e não cria o diretório de saída:

```bash
uv run banca-revista batch-to-cbr
```

Revise cuidadosamente o plano: a pasta atual também contém livros PDF que não são quadrinhos. Formatos não suportados
ficam registrados como `unsupported`, sem serem alterados. Para executar:

```bash
uv run banca-revista batch-to-cbr --execute
```

Cada falha é isolada e registrada. Saídas existentes são marcadas como `skipped`; os itens seguintes continuam sendo
processados. O primeiro relatório é `conversion-report.json`; lotes posteriores usam sufixos sequenciais sem
sobrescrever o histórico. Sem `--remove-originals`, a pasta de origem permanece intacta: "mover" neste fluxo
significa publicar a cópia processada em `~/banca` após as validações.

### Remoção dos originais publicados

Com `--remove-originals`, ao fim da execução os originais publicados com sucesso vão para a Lixeira do usuário
(`$XDG_DATA_HOME/Trash`, especificação freedesktop.org), de onde podem ser restaurados pelo gerenciador de arquivos.
Na origem ficam apenas os arquivos que exigem atenção.

- Só itens `processed` nesta execução saem. `failed`, `unsupported` e `skipped` ficam: `skipped` é decidido pelo
  nome da saída, não pelo conteúdo, e por isso não prova que aquele original está em `~/banca`.
- Um contêiner sai só depois que todos os quadrinhos extraídos dele saíram; vale também para contêineres aninhados.
- A remoção é feita por `link` + `unlink`, com o nome reservado pelo `.trashinfo`: nunca copia, nunca apaga em
  definitivo e nunca sobrescreve um item da Lixeira (nomes repetidos recebem sufixo `.2`, `.3`...).
- Exige que a origem esteja na mesma partição da Lixeira. Se o envio falhar, o original fica, o item continua
  `processed` e o motivo aparece no relatório (`original mantido: ...`) e na tabela de originais mantidos.
- A simulação nunca remove nada; com a opção, ela apenas informa que a remoção está ativa.

```bash
uv run banca-revista batch-to-cbr --execute --remove-originals
```

Por padrão, até 10 arquivos percorrem seus pipelines completos em processos independentes. As etapas de um arquivo
são sequenciais porque normalização, OCR, enriquecimento e publicação dependem da etapa anterior. Arquivos diferentes
avançam em paralelo, podem terminar fora de ordem e permanecem na ordenação natural do relatório:

```bash
uv run banca-revista batch-to-cbr \
  "/home/boladuz/Downloads/Telegram Desktop" \
  ~/banca \
  --execute \
  --workers 10
```

Use um valor menor quando memória, disco ou limites de serviços externos forem mais restritos. `--no-lookup-isbn`
evita consultas ao catálogo durante o lote e elimina o risco de limitação de requisições pelo serviço.

O relatório inclui os metadados efetivamente gravados. Se as duas primeiras imagens não contiverem um ISBN legível,
o arquivo ainda é publicado com os campos confiáveis obtidos do nome e recebe um aviso explícito no relatório.

O comando não cria CBRs criptografados. Para corrigir saídas de uma versão anterior, `--replace-existing` mantém o
arquivo atual até a nova cópia sem senha passar por todas as validações e então realiza uma substituição atômica.

Durante a execução, barras coloridas apresentam o progresso total e por fase, percentual, quantidade concluída, tempo
decorrido, workers ativos, fila restante e a etapa de cada arquivo em andamento. O painel de encerramento separa
sucessos, avisos, arquivos ignorados, falhas e ISBNs encontrados. Use `--json` quando outro programa precisar consumir
a saída; o relatório em arquivo continua sendo salvo normalmente nas execuções.

## Validação

Antes de publicar a saída, a ferramenta:

1. testa CRC do ZIP ou integridade do RAR;
2. rejeita caminhos absolutos e travessia por `..`;
3. cria o RAR em diretório temporário no mesmo filesystem do destino;
4. testa integralmente o RAR criado;
5. compara ordem, quantidade e SHA-256 de todas as páginas;
6. publica sem uma janela de sobrescrita.

Nos testes reais desta etapa:

```text
Prometheus - Fogo e Pedra 01.pdf
  estratégia: pdf-lossless
  páginas: 22

Wolverine - O Fim.zip
  estrutura: 6 CBRs internos
  estratégia: zip-nested-cbr (substituída pela extração de contêineres)
  páginas finais: 149
```

O Calibre reconheceu a primeira página como capa nos dois resultados, e o SHA-256 da capa extraída foi idêntico ao
primeiro membro do respectivo CBR.

# Capas ausentes no Calibre — arquivos `CBR` e `CBZ`

> Este documento registra o diagnóstico de quadrinhos e mangás cuja primeira página não é reconhecida como capa pelo
> Calibre, além do procedimento seguro para normalizar esses arquivos.

## Problema observado

Ao importar coleções de HQs e mangás, o Calibre recupera corretamente a primeira página como capa de alguns arquivos
`CBR`, mas não de outros.

Um exemplo que apresenta o problema é:

```text
/mnt/storage/Biblioteca do calibre/Volume 01 [Packs de HQs]/SIDOOH (84)/
SIDOOH - Volume 01 [Packs de HQs].cbr
```

O arquivo abre como uma revista em quadrinhos e contém todas as páginas, mas as imagens estão dentro de uma pasta
interna. A inspeção automatizada confirmou essa estrutura e também identificou uma limitação mais direta na instalação
local do Calibre: o módulo usado para ler RAR não está disponível.

## Como o Calibre obtém a capa

O Calibre possui um leitor interno de metadados para quadrinhos. Ao importar arquivos `CBR`, `CBZ`, `CB7` ou `CBC`, ele
tenta localizar e extrair uma imagem do arquivo para usá-la como capa.

Para que isso aconteça durante a importação, confira a opção equivalente a:

```text
Preferências → Adicionar livros → Ler metadados do conteúdo do arquivo em vez do nome do arquivo
```

O nome exato pode variar conforme a versão e a tradução do Calibre.

Arquivos já cadastrados podem conservar a capa anterior no catálogo. Alterar a preferência não garante que todos os
itens existentes sejam reprocessados automaticamente.

## Diagnóstico confirmado

A estrutura problemática possui uma pasta externa dentro do `CBR`:

```text
SIDOOH - Volume 01.cbr
└── SIDOOH - Volume 01/
    ├── 000.jpg
    ├── 001.jpg
    └── 002.jpg
```

O formato mais compatível coloca as imagens diretamente na raiz do arquivo:

```text
SIDOOH - Volume 01.cbz
├── 000.jpg
├── 001.jpg
└── 002.jpg
```

No arquivo piloto, foram observados os seguintes fatos:

- o conteúdo é RAR 5 válido, e não um ZIP apenas renomeado;
- o teste integral do RAR termina sem erros;
- existem 218 imagens JPG, todas dentro de uma única pasta interna;
- a ordenação natural começa em `(000).jpg`, segue de `(200).jpg` a `(416).jpg` e não deve ser renumerada;
- o Calibre 9.13 local não extrai a capa do CBR porque o módulo Python `unrardll` não está instalado.

O leitor atual do Calibre aceita nomes de imagens dentro de subpastas. Portanto, a pasta interna isoladamente não
explica a falha reproduzida nesta instalação. Ainda assim, achatar as páginas reduz diferenças entre leitores. A
conversão para `CBZ` é a correção decisiva porque usa ZIP, que o Calibre lê sem depender do suporte a RAR.

## Outras causas possíveis

Se remover a pasta interna não resolver, verifique também:

- arquivo ZIP apenas renomeado para `.cbr`, quando a extensão correta seria `.cbz`;
- compactação RAR não suportada pela instalação do Calibre;
- arquivo protegido por senha, incompleto ou corrompido;
- primeira imagem em formato incomum, inválida ou com extensão incorreta;
- nomes que não produzem a ordem esperada, como `1.jpg`, `10.jpg` e `2.jpg`;
- capa antiga já armazenada no catálogo do Calibre.

## Como confirmar o diagnóstico

Abra o arquivo problemático no PeaZip, 7-Zip File Manager, Ark ou Gerenciador de compactação e confira:

1. Qual é o formato real do arquivo: RAR ou ZIP.
2. Se as imagens estão na raiz ou dentro de uma pasta.
3. Se a primeira imagem é realmente a capa.
4. Se as páginas usam formatos comuns, como `JPG`, `JPEG`, `PNG` ou `WEBP`.
5. Se o arquivo pode ser extraído integralmente sem erros ou solicitação de senha.

Se o quadrinho abrir no visualizador do Calibre, mas não gerar capa, a estrutura, a ordenação das imagens ou o cache
do catálogo são as hipóteses principais. Se nem sequer abrir, investigue o formato real, a compactação, a senha ou uma
possível corrupção.

## Correção automatizada

O projeto contém uma interface que inspeciona o RAR sem modificá-lo:

```bash
uv run banca-revista inspect "/caminho/arquivo.cbr"
```

Para criar um novo `CBZ`:

```bash
uv run banca-revista convert "/caminho/arquivo.cbr" "/caminho/resultado.cbz"
```

O comando:

1. detecta o formato real pelo cabeçalho;
2. testa integralmente o RAR com `unrar` e senha vazia;
3. rejeita caminhos inseguros e nomes que colidiriam ao remover pastas;
4. ordena as páginas naturalmente sem renomeá-las;
5. transmite cada imagem diretamente do RAR para um ZIP temporário;
6. compara SHA-256, ordem e CRC das páginas;
7. publica o `.cbz` de forma atômica sem sobrescrever arquivos existentes.

Arquivos não-imagem não são copiados para o `CBZ`. A origem permanece inalterada.

## Correção manual com o PeaZip

É preferível recriar o quadrinho como `CBZ`. Esse formato é um arquivo ZIP de imagens e normalmente possui
compatibilidade mais previsível que `CBR`/RAR.

1. Faça uma cópia do `CBR` original em uma pasta temporária fora da biblioteca administrada pelo Calibre.
2. Abra ou extraia essa cópia com o PeaZip.
3. Entre na pasta interna que contém as páginas.
4. Confirme a sequência das imagens; só renomeie quando houver evidência de ordenação incorreta.
5. Selecione as imagens, e não a pasta que as contém.
6. Escolha **Adicionar ao arquivo** e use o formato ZIP.
7. Renomeie a extensão do resultado de `.zip` para `.cbz`.
8. Abra o novo `CBZ` e confirme que as imagens estão na raiz, na ordem correta e legíveis.

Uma sequência recomendada é:

```text
000_capa.jpg
001.jpg
002.jpg
003.jpg
```

O preenchimento com zeros evita que leitores com ordenação puramente alfabética coloquem `10.jpg` antes de `2.jpg`.
Não renumere lacunas automaticamente: números ausentes podem ser intencionais.

## Validação do arquivo piloto

O arquivo piloto foi convertido fora da origem e da biblioteca do Calibre. O resultado observado no CBZ foi:

```text
páginas: 218
primeira página: (000).jpg
última página: (416).jpg
entradas na raiz: sim
teste CRC do ZIP: aprovado
capa extraída pelo Calibre: idêntica à primeira página
```

O SHA-256 da capa extraída pelo Calibre e o da primeira entrada do `CBZ` foram ambos
`8a147485eeab57ef91198d1b94cae6bedf2425fb0b7961241b9c3c9e0a442c79`.

A validação automatizada comprova a correção da extração de capa. A persistência da capa no catálogo após reiniciar a
interface gráfica ainda depende da importação manual no catálogo do usuário.

Depois dessa validação, as mesmas páginas também foram recompactadas como RAR 5, com extensão `.cbr`, e salvas em
`pilotos/`, pasta local ignorada pelo Git. O CBR possui 218 páginas na raiz e na mesma ordem. O SHA-256 de cada página é
idêntico ao CBZ usado como referência.

O pacote Python `unrardll` instalado no ambiente `uv` não é carregado pelo Calibre do openSUSE, pois cada um usa seu
próprio interpretador Python. Além disso, a `libunrar.so.7.2.6` instalada foi diagnosticada com símbolos C++ internos
não resolvidos. O plugin abaixo contorna essas duas limitações usando o executável `unrar` do sistema.

## Plugin para o Calibre do openSUSE

O plugin versionado em `calibre_plugins/cbr_cover_unrar/` substitui somente a leitura de metadados de arquivos `CBR`.
Ele lista as páginas sem extraí-las em disco, seleciona a primeira imagem por ordenação natural e envia seus bytes ao
Calibre como capa. Título e autor continuam sendo derivados pelo fluxo normal do Calibre a partir do nome do arquivo.

Crie o ZIP com o arquivo `__init__.py` na raiz do pacote:

```bash
cd calibre_plugins/cbr_cover_unrar
python3 -m zipfile -c /tmp/cbr-cover-unrar.zip __init__.py
```

Instale e confirme o registro do plugin:

```bash
calibre-customize --add-plugin /tmp/cbr-cover-unrar.zip
calibre-customize --list-plugins
```

Feche todas as janelas do Calibre antes da instalação e abra o programa novamente. Novos `CBR` importados passam a
receber a capa automaticamente. Para um livro já presente no catálogo, remova-o e importe-o novamente, ou solicite ao
Calibre que releia os metadados do formato; não é necessário escolher uma imagem manualmente.

No teste com a configuração real do Calibre 9.13 do openSUSE, o plugin extraiu automaticamente a capa do CBR piloto.
O arquivo retornado manteve o SHA-256 `8a147485eeab57ef91198d1b94cae6bedf2425fb0b7961241b9c3c9e0a442c79`,
idêntico ao da primeira página `(000).jpg`.

## OCR e metadados incorporados

O comando `ocr` extrai temporariamente somente as primeiras páginas selecionadas e executa Tesseract localmente. As
imagens não são enviadas a serviços externos. O resultado JSON conserva o texto reconhecido, a página de origem e a
confiança de cada candidato:

```bash
uv run banca-revista ocr "/caminho/revista.cbr" --pages 2
```

Com `--lookup-isbn`, somente o ISBN validado é enviado ao catálogo oficial da Biblioteca Nacional do Japão (NDL).
As imagens e os textos completos do OCR permanecem locais:

```bash
uv run banca-revista ocr "/caminho/revista.cbr" --lookup-isbn
```

No piloto, a análise confirmou automaticamente:

```text
título: SIDOOH (nome do arquivo, confiança 0,98)
volume: 01 (nome do arquivo, confiança 0,99)
ISBN: 9784088768120 (segunda imagem e checksum válido, confiança 0,99)
autor: candidatos aproximados (capa, confiança 0,55)
autor oficial: 高橋ツトム (catálogo NDL pelo ISBN, confiança 0,99)
editora da edição do ISBN: 集英社 (catálogo NDL, confiança 0,99)
```

O nome estilizado `Tsutomu Takahashi` não foi reconhecido integralmente em todas as variações. Por isso, o sistema o
mantém como candidato, sem gravá-lo automaticamente. Um campo com confiança baixa precisa ser confirmado ou cruzado
com uma fonte bibliográfica antes de ser promovido a metadado.

Depois da confirmação, o comando `metadata` cria uma nova cópia e grava um documento `ComicBookInfo/1.0` no comentário
do RAR:

```bash
uv run banca-revista metadata origem.cbr resultado.cbr \
  --title "SIDOOH - Volume 01" \
  --author "Tsutomu Takahashi" \
  --series "SIDOOH" \
  --volume 1 \
  --isbn 9784088768120 \
  --publisher "Panini Comics" \
  --tag "Mangá" \
  --tag "Ação"
```

A origem nunca é alterada e uma saída existente não é sobrescrita. O plugin na versão 1.1.0 lê o comentário e
entrega ao Calibre título, autores, série, volume, ISBN, editora, tags, comentários e a primeira imagem como capa.

O comando `enrich` une OCR, consulta por ISBN e criação da cópia em uma operação:

```bash
uv run banca-revista enrich origem.cbr resultado.cbr \
  --author "Tsutomu Takahashi" \
  --publisher "Panini Comics" \
  --tag "Mangá"
```

O ISBN do piloto aponta para a edição japonesa da Shueisha, enquanto a capa usada no arquivo mostra Panini/Planet
Manga. O catálogo confirma os dados ligados ao ISBN, mas não decide qual edição visual deve prevalecer. Use
`--publisher` para registrar conscientemente a editora mostrada na capa.

## Atualização segura no Calibre

> Não edite diretamente arquivos dentro de `Biblioteca do calibre`. O Calibre administra nomes, diretórios, formatos e
> referências nessa pasta; alterações externas podem ser sobrescritas ou deixar o catálogo inconsistente.

Depois de validar o novo `CBZ`:

1. Selecione o livro no Calibre.
2. Abra **Editar metadados**.
3. Use **Adicionar formato** para anexar o novo `CBZ` ao mesmo registro.
4. Solicite a atualização da capa a partir do formato do livro, se ela não aparecer automaticamente.
5. Feche e reabra a edição de metadados para confirmar que a capa foi salva.
6. Abra o `CBZ` pelo Calibre e confira a ordem de todas as páginas.
7. Remova o formato `CBR` pelo próprio Calibre somente depois de confirmar o resultado e preservar um backup.

Os rótulos dos comandos podem variar entre versões, sistemas operacionais e traduções do programa.

## Critérios de sucesso

A normalização está concluída quando:

- o novo arquivo possui extensão `.cbz` e conteúdo ZIP válido;
- as imagens estão diretamente na raiz do arquivo;
- a capa é o primeiro arquivo na ordenação;
- o quadrinho abre sem erros e mantém todas as páginas na ordem correta;
- o Calibre exibe a primeira página como capa;
- a capa continua correta após reiniciar o Calibre;
- o arquivo original permanece disponível como backup até a validação final.

## Referências

- [Leitor de quadrinhos do Calibre](https://github.com/kovidgoyal/calibre/blob/master/src/calibre/customize/builtins.py)
- [Índice oficial de plugins do Calibre](https://plugins.calibre-ebook.com/)

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
interna. Essa diferença de estrutura explica por que a extração automática da capa pode falhar.

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

## Causa identificada

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

Há relatos de que a extração de capa funciona quando as imagens estão na raiz, mas falha em determinados arquivos com
imagens em níveis mais profundos. Portanto, a pasta interna é a causa mais provável neste caso.

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

## Correção recomendada com o PeaZip

É preferível recriar o quadrinho como `CBZ`. Esse formato é um arquivo ZIP de imagens e normalmente possui
compatibilidade mais previsível que `CBR`/RAR.

1. Faça uma cópia do `CBR` original em uma pasta temporária fora da biblioteca administrada pelo Calibre.
2. Abra ou extraia essa cópia com o PeaZip.
3. Entre na pasta interna que contém as páginas.
4. Confirme a sequência das imagens e renomeie-as, se necessário, com preenchimento de zeros.
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

O preenchimento com zeros evita que uma ordenação alfabética coloque `10.jpg` antes de `2.jpg`.

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

- [Código do leitor de metadados de quadrinhos do Calibre](https://github.com/kovidgoyal/calibre/blob/master/src/calibre/customize/builtins.py)
- [Índice oficial de plugins do Calibre](https://plugins.calibre-ebook.com/)

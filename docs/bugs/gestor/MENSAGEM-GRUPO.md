# Mensagem para o grupo (rascunho no estilo do Pedro)

> pessoal, testei o gestor essa semana (o acessilia web) como o professor e o @master_jf pediram. usei os 4 logins de teste, rodei uns testes automatizados no navegador e confirmei na mão os principais. subi uns .md com os detalhes e prints.
>
> resumo do que achei:
>
> controle de acesso: tem uns furos. logado como aluno eu consigo baixar o csv com a lista de materiais (com nome dos professores) e abrir material de qualquer professor só trocando o id na url tipo /materiais/1, /2, /3 - inclusive um que tava com um .exe anexado. a parte de criar (post) tá protegida, é só a leitura que vaza mesmo.
>
> fluxo do material: subi uma imagem, ela fica presa em PROCESSANDO e nenhum dos downloads (html, pdf, docx, txt, mp3, zip) funciona, dá 404. o leitor mostra um texto padrão, não o conteúdo real. imagino que seja a integração com o core que ainda tá mockada, então mais um ajuste de documentação (marcar como em desenvolvimento) do que bug.
>
> acessibilidade: a barra e as opções funcionam, mas o contraste não bate os 7:1 do AAA que tá escrito (uns 19 pontos ficam entre 4.5 e 5.9). daria pra escurecer o texto cinza ou baixar a alegação pra AA, que já é forte.
>
> uns detalhes: a tela de materiais estica quando o título é muito longo (em vez de cortar), o cookie de sessão tá sem a flag Secure, e o login não trava depois de várias senhas erradas (só o limite geral).
>
> coisas boas: o csrf tá funcionando, rota sem login manda pro login certinho e o sse volta 401. no geral tem bastante coisa pronta, parabéns @master_jf.
>
> deixei uma sugestão em cada ponto nos .md. lembrando que sou só tester, não mexi no código - fica a cargo de vocês.

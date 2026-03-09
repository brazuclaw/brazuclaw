# Lista de Skills

Este arquivo contém o resumo de todas as skills disponíveis no BrazuClaw. Consulte as skills aqui listadas sempre que precisar realizar uma tarefa que se enquadre em um dos escopos abaixo.

## Skills Disponíveis

- **how-to-make-new-skills**: Instruções e boas práticas sobre como criar novas skills compatíveis com múltiplos provedores de IA. Ensina a estrutura de diretório exigida e os padrões recomendados para a criação de documentações (`skill.md`) e ferramentas auxiliares.
- **chrome-desktop**: Controla o Chrome real do desktop via CDP (Chrome DevTools Protocol) com perfil dedicado em `~/.brazuclaw/agent-chrome/`. Metodo padrao para qualquer tarefa web — verificar se Chrome CDP esta ativo em `localhost:9222`, iniciar se necessario, e usar endpoints HTTP e websocket do CDP para navegar, interagir e capturar screenshots. O Chrome deve permanecer aberto entre tarefas. Playwright so deve ser usado se o usuario pedir explicitamente.

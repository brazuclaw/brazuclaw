# Como criar novas Skills

Esta skill serve como um guia para a criação de novas skills no BrazuClaw. Múltiplos agentes de diferentes provedores (OpenAI, Anthropic, Google, etc) consumirão essas skills, portanto as instruções devem ser genéricas, claras e agnósticas a modelos específicos.

## Estrutura de uma Skill
Toda skill **deve** ter seu próprio diretório dentro de `~/.brazuclaw/skills/`.
Dentro desse diretório, a documentação principal da skill deve estar no arquivo `skill.md`.

Exemplo:
`~/.brazuclaw/skills/nome-da-sua-skill/skill.md`

Se houver scripts auxiliares de CLI ou outros arquivos necessários, coloque-os dentro do mesmo diretório e documente como executá-los em `skill.md`.

## Boas Práticas
1. **Clareza de Propósito:** O arquivo `skill.md` deve deixar muito claro o objetivo da skill logo no início.
2. **Contexto Completo:** Explique como a skill funciona, de onde lê dados, onde escreve, e quais ferramentas externas pode precisar usar (comandos bash, sqlite, python, etc).
3. **Compatibilidade Multi-Agente:** Evite jargões ou instruções específicas de uma IA (como "use a ferramenta do Claude x"). Prefira explicar a tarefa abertamente para que qualquer LLM consiga entender o fluxo.
4. **Registro:** Após criar ou modificar uma skill, você deve atualizar o arquivo `~/.brazuclaw/skills/skill-list.md`, adicionando o nome da nova skill e um resumo de sua finalidade para que o BrazuClaw conheça o catálogo.

# Lab « dérive de VLANs » : un agent Strands entre NetBox et des switchs Containerlab

Document de conception, 22 octobre 2026. Repo compagnon d'un article de blog sur Strands Agents (exploration).
Le lecteur clone le repo, lance `install.sh`, suit l'article, et voit un agent auditer puis corriger des VLANs sur de
vrais switchs, avec NetBox comme source de vérité. L'article lui-même n'est pas dans ce repo.

## Intention et pourquoi

L'article veut montrer ce qu'un agent Strands apporte sur un cas réseau que tout ingénieur reconnaît, pas sur un jouet.
Le cas : la configuration des switchs dérive de ce que NetBox dit qu'elle devrait être. L'agent lit les deux côtés,
rapporte l'écart, puis corrige, encadré par des gardes écrites en code et pas seulement demandées au modèle.

Un seul objet métier, la VLAN, traverse tout l'article. Le lecteur n'a qu'un concept à suivre ; la complexité est dans
la mécanique de l'agent, c'est elle qu'on veut lui faire voir.

Le récit se joue en deux temps, le même agent recevant un peu plus de pouvoir au second :

1. **Audit** (lecture seule) : l'agent lit les VLANs attendues dans NetBox, interroge les switchs par SSH, et rend un
   tableau des écarts. Deux serveurs MCP coopèrent sous un seul agent.
2. **Remédiation** (écriture sur les switchs) : l'agent propose les commandes qui ramènent chaque switch à l'état
   NetBox, l'utilisateur confirme, les commandes partent. Les gardes font le travail intéressant : seules les commandes
   `vlan N` et `name X` passent, jamais un `no vlan`. L'agent ajoute, l'humain retire.

Ce que l'article montre de Strands, dans l'ordre d'apparition : `Agent` + `AnthropicModel`, outils MCP (`MCPClient`),
skills (`AgentSkills`, la procédure d'audit), un outil maison (`@tool`), hooks (`BeforeToolCallEvent` pour confirmer,
`AfterToolCallEvent` pour tracer), steering (`SteeringHandler` + `LedgerProvider`, la liste blanche et la limite par
tour).

## Buts

- `sh install.sh` monte toute la pile sur une machine Linux propre, sans autre action que poser l'image cEOS, et se
  rejoue sans casser ce qui existe.
- Les trois écarts sont introduits par un script séparé, rejouable, pour que la démo soit reproductible à volonté.
- L'agent fonctionne tel quel avec le lecteur : `uv run python agent.py` puis les deux questions de l'article.
- Tout le code vu dans l'article vient de ce repo, sans adaptation.
- Le README dit clairement que la lecture des switchs passe par `netmiko_mcp`, le serveur officiel de l'auteur de
  Netmiko, et pourquoi l'écriture passe par un outil maison.

## Non-buts

- Pas de fabric complète : deux leafs suffisent, pas de spine, pas de routage.
- Pas d'écriture dans NetBox dans le fil principal. Les hooks NetBox existants (confirmation, lien vers l'objet écrit)
  restent dans le code, et la VLAN 99 en trop donne un épilogue naturel (« veux-tu la documenter dans NetBox ? »),
  mais l'article ne s'y attarde pas.
- Pas de multi-agent, pas de mémoire, pas d'évaluation. Un agent, un terminal.
- Pas d'interface web. Le chat se fait dans le terminal, comme l'agent existant de `strand_agents_lab`.

## Anti-buts

- Un lecteur qui doit bricoler `install.sh` pour que ça marche. Si une étape ne peut pas être automatisée (l'image
  cEOS), le script la détecte, dit quoi faire, et s'arrête proprement.
- Un agent qui supprime quelque chose sur un switch, même une fois, même après confirmation. Le steering refuse les
  suppressions sans exception ; la confirmation n'est pas une porte de sortie.
- Un repo qui porte des traces du lab interne (`strand_agents_lab`) : noms d'équipements, champs custom, utilisateurs,
  jeux de tests, mais aussi le `name:` du projet Compose, le token superuser codé en dur, le fuseau horaire et les
  mots de passe de `seed.py`. Le code en est inspiré, les données non.

## Contraintes

- **`netmiko_mcp` est en lecture seule.** Version 0.2.0 sur PyPI (la branche `main` se dit 0.3.0 mais n'est pas
  publiée ; ses deux commits ne touchent que les dépendances et le transport HTTP). Outils `list_devices`, `list_groups`, `send_show_command`,
  `send_show_command_to_group`, `read_device_output`, `ping`. Pas de mode config, et son TODO le réserve à un futur
  drapeau opt-in. D'où l'outil maison pour l'écriture. Il exige trois fichiers : une config (`inventory_file`,
  `command_file`), un inventaire au format Netmiko Tools (`.netmiko.yml`, identifiants en clair acceptables pour un
  lab), et une liste blanche de commandes où tout est refusé par défaut (globs `*`, `denied_commands` prioritaire).
  Installation par `uv tool install netmiko-mcp==0.2.0`. Décision de ce document : on épingle la version PyPI, pas un
  commit Git, pour que la ligne d'installation du lecteur soit une ligne ordinaire.
- **L'image cEOS n'est pas téléchargeable par script.** Arista la fournit derrière un compte gratuit. Le lecteur la pose
  dans `images/` ; `install.sh` fait le `docker import` et le tag. Le script accepte les noms `cEOS64-lab-*`,
  `cEOS-lab-*` (x86_64, selon la version téléchargée) et `cEOSarm-lab-*` (ARM, EFT) ; le README ne documente que la
  cible x86_64 et mentionne l'ARM en une ligne, sans promesse.
- **Containerlab est un outil Linux.** Cible du lecteur : Linux x86_64 (Ubuntu 22.04 ou 24.04) avec Docker. Sur Apple
  Silicon il faut une VM Linux arm64 (OrbStack) et la version ARM de cEOS, encore marquée EFT et au support limité.
  Le README annonce la cible Linux et renvoie vers la page macOS de Containerlab pour les autres.
- **`netbox-mcp-rw`** (alexkiwi1) est cloné à un commit épinglé avec son propre venv Python 3.13, comme aujourd'hui.
  Son `netbox_bulk_update_objects` est cassé ; on ne l'utilise pas.
- **Clé API Anthropic** dans l'environnement du lecteur (`ANTHROPIC_API_KEY`). Le README le dit et donne un ordre de
  grandeur du coût d'une session de démo, mesuré lors des tests.
- Le repo est public, en anglais (code, README, skills, system prompt) ; l'article est en français et traduit ce qu'il
  cite. Décision du commanditaire.

## Le scénario, précisément

### Décor

NetBox connaît un site `lab`, deux switchs d'accès Arista `leaf1` et `leaf2` (type d'équipement cEOS-lab, plateforme
Arista EOS, IP de management primaire), et trois VLANs portées par le site :

| VID | Nom   |
|-----|-------|
| 10  | USERS |
| 20  | VOICE |
| 30  | IOT   |

Chaque leaf a trois ports d'accès `Ethernet1`, `Ethernet2`, `Ethernet3`, en mode access, untagged sur 10, 20 et 30
respectivement. Cela donne à l'agent une raison de regarder les interfaces, pas seulement la table des VLANs, et une
extension possible de l'article (dérive de port) sans changer le décor.

Les deux leafs cEOS démarrent avec une startup-config propre, identique à NetBox : les trois VLANs nommées, les trois
ports d'accès, SSH actif avec `admin`/`admin`, management sur le réseau Containerlab avec des adresses fixes
(`172.20.20.11` et `172.20.20.12`, les mêmes que dans NetBox).

### La dérive (`drift.sh`)

Trois écarts, trois natures, appliqués par `docker exec ... Cli` sur les conteneurs, rejouables :

| Où    | Écart                                   | Nature     | Ce que l'agent fera                     |
|-------|-----------------------------------------|------------|-----------------------------------------|
| leaf1 | la VLAN 30 n'existe pas                 | manquant   | `vlan 30` / `name IOT`                  |
| leaf2 | la VLAN 20 s'appelle `VOIP`             | différent  | `vlan 20` / `name VOICE`                |
| leaf2 | une VLAN 99 `LEGACY` que NetBox ignore  | en trop    | la signaler ; refuser de la supprimer   |

`drift.sh` est idempotent et affiche l'état après coup (`show vlan` des deux leafs) pour que le lecteur voie la dérive
avant de lancer l'agent. `drift.sh --reset` ramène les leafs à l'état propre à partir des fichiers du repo
(`clab/leafN.cfg`, par `configure replace` ou `containerlab deploy --reconfigure`), et surtout pas à partir de la
startup-config du switch : l'outil de remédiation fait `write memory`, donc après une démo la startup-config du
conteneur contient la VLAN 99. C'est ce qui permet de rejouer la démo.

### Audit

Question posée : « Audit the VLANs of site lab against the switches. »

Le skill `vlan-audit` donne la procédure : lister les VLANs du site dans NetBox (`netbox_get_objects` sur `vlans` avec
le filtre `site`), lister les équipements du site, pour chacun lancer `show vlan` par `send_show_command` (TextFSM
activé pour obtenir du structuré), comparer VID et nom, et rendre un tableau par équipement : VLAN attendue,
observée, verdict (ok / missing / renamed), plus une ligne par VLAN présente sur le switch et absente de NetBox.

Seule commande autorisée dans `commands.yml` : `show vlan*`. L'article fait remarquer que c'est `netmiko_mcp` qui
refuse tout le reste, côté serveur, avant même que les gardes de l'agent n'entrent en jeu.

### Remédiation

Question posée : « Fix leaf1 and leaf2 so they match NetBox. »

L'agent repart de l'audit (il est dans la conversation), propose pour chaque leaf les commandes, et appelle l'outil
maison `configure_vlans(device, commands)`. Trois choses se passent dans l'ordre, et l'article les montre dans cet
ordre :

1. **Steering** (`VlanGuard`, un `SteeringHandler`) : chaque commande doit matcher `vlan <1-4094>` ou
   `name <mot de 1 à 32 caractères alphanumériques, tiret, souligné>`. Toute autre commande, `no vlan 99` en tête,
   refuse l'appel entier avec une raison renvoyée au modèle (« deletions are not allowed ; report it to the user
   instead »). Un plafond de VLANs touchées par tour (5) borne un modèle qui boucle. Le ledger compte sur le tour
   courant, comme `LimitDeletes` aujourd'hui.
2. **Hook de confirmation** (`ConfirmDeviceWrites`, `BeforeToolCallEvent`) : affiche l'équipement et les commandes,
   attend un `y`. Il s'exécute après le steering (priorité `HookOrder.SDK_LAST`), pour que l'utilisateur ne confirme
   jamais quelque chose qui sera refusé juste après.
3. **L'outil** : charge l'inventaire `.netmiko.yml`, le même fichier que `netmiko_mcp`, résout `device`, ouvre une
   session Netmiko `arista_eos`, `send_config_set(commands)`, `save_config()`, et renvoie la sortie. Un équipement
   inconnu de l'inventaire est une erreur de l'outil, pas une garde.

Résultat attendu : leaf1 retrouve la VLAN 30, leaf2 renomme la 20, la 99 reste et l'agent écrit qu'il ne la supprime
pas et propose de la documenter dans NetBox. Le lecteur relance l'audit : plus que la 99 en écart, et c'est voulu.

## Ce que `install.sh` fait

Un seul point d'entrée, idempotent, étapes numérotées avec un en-tête, checks à la fin, sortie non nulle au premier
problème. Modelé sur l'`install.sh` de `strand_agents_lab`.

0. **Prérequis** : Docker + Compose v2 accessibles sans `sudo` (groupe `docker`), `containerlab`, `uv`, `git`, et une
   archive cEOS dans `images/`. Chaque manque est nommé avec la commande ou le lien pour y remédier ; `containerlab`
   absent affiche la ligne d'installation officielle sans l'exécuter. `containerlab deploy` exige root ou le groupe
   `clab_admins` : `sudo` n'est utilisé que pour les étapes Containerlab, jamais pour `uv`, `.env` ou le venv, qui
   doivent rester à l'utilisateur.
1. **NetBox** : `docker compose up -d`, attente du login (port `NETBOX_PORT`, défaut à choisir par le builder), token
   superuser, tokens MCP lecture et lecture-écriture régénérés ou conservés depuis `.env`. Le sous-réseau du réseau
   Compose est fixé explicitement, à l'écart du `172.20.20.0/24` de Containerlab, pour que l'ordre des étapes ne
   compte pas.
2. **Seed NetBox** (`netbox/seed.py`, REST, `get_or_create`) : site, constructeur, type d'équipement, rôle,
   plateforme, les deux leafs avec IP de management, les trois VLANs, les interfaces et leur VLAN d'accès, les
   utilisateurs `mcp` (lecture) et `mcp-rw` (ajout/modification sur VLANs et interfaces, pas de suppression) et leurs
   tokens.
3. **`netbox-mcp-rw`** cloné et épinglé, venv Python 3.13.
4. **`netmiko-mcp`** : `uv tool install netmiko-mcp==<version épinglée>` ; génération dans `netmiko/` de
   `netmiko-mcp.yml`, `.netmiko.yml` (leaf1, leaf2, `arista_eos`, admin/admin, hôtes 172.20.20.11/12) et
   `commands.yml` (`show vlan*` seulement) ; journal d'audit dirigé dans `netmiko/audit.log`.
5. **Containerlab** : `docker import` de l'archive cEOS vers `ceos:<version>` si le tag manque, puis
   `containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure`. Attente que les deux leafs répondent en SSH (cEOS
   met une à deux minutes à monter).
6. **Agent** : `uv sync` du projet ; écriture de `.mcp.json` (serveurs `netbox` et `netmiko`, utilisables aussi dans
   Claude Code).
7. **Checks** : NetBox compte trois VLANs sur le site ; le token lecture ne peut pas écrire ; `show vlan` par Netmiko
   sur chaque leaf contient `USERS`, `VOICE`, `IOT` ; `netmiko-mcp` démarre avec la config générée.

`uninstall.sh` détruit la topologie, arrête NetBox (`-v` pour effacer les données), et laisse les images.

## Structure du repo

```
README.md                  quoi, pourquoi, prérequis, install, les deux questions, où est quoi, netmiko_mcp expliqué
install.sh  drift.sh  uninstall.sh
docker-compose.yml         NetBox 4.4.x, Postgres, Redis, worker
netbox/                    seed.py, bootstrap_token.sh, netbox.env
clab/                      vlan-lab.clab.yml, leaf1.cfg, leaf2.cfg (startup-configs propres)
netmiko/                   généré par install.sh : netmiko-mcp.yml, .netmiko.yml, commands.yml, audit.log (git-ignorés)
images/                    l'archive cEOS posée par le lecteur (git-ignoré)
agent.py                   l'agent : modèle, MCP, skills, outil maison, hooks, steering, boucle de chat
tools/netmiko_config.py    configure_vlans, l'outil maison
guards/                    ConfirmDeviceWrites, VlanGuard, et les hooks NetBox repris de strand_agents_lab
skills/vlan-audit/SKILL.md
skills/vlan-remediation/SKILL.md
.mcp.json  .env.example  pyproject.toml  uv.lock
docs/superpowers/specs/    ce document
```

Le découpage `agent.py` / `tools/` / `guards/` suit l'ordre de lecture de l'article : le lecteur ouvre un fichier par
section. Le builder peut regrouper si les fichiers deviennent trop petits pour mériter d'exister.

## Décisions prises ici (à contester, pas à redécouvrir)

- **cEOS** plutôt que SR Linux : `show vlan` et la syntaxe `vlan N / name X` sont celles qu'un lecteur réseau attend ;
  SR Linux n'a pas de table de VLANs classique. Prix : l'image à télécharger soi-même.
- **Deux leafs, pas de spine** : assez pour avoir deux dérives différentes, pas plus de bruit.
- **Outil maison pour l'écriture**, pas un fork de `netmiko_mcp` : montre `@tool` à côté de MCP, et c'est sur lui que
  les gardes de l'agent s'exercent. Validé avec le commanditaire.
- **Même inventaire** `.netmiko.yml` pour `netmiko_mcp` et l'outil maison : un seul endroit pour les identifiants.
- **Le steering refuse, le hook demande** : la confirmation ne peut pas débloquer une commande refusée.
- **Commandes en anglais** dans l'article et les skills : les modèles les suivent mieux, et le repo est anglophone.
- **Même modèle Anthropic** que l'agent de `strand_agents_lab`, par `AnthropicModel`.

## Laissé au builder

- Les versions exactes à épingler (NetBox 4.4.x, `netmiko-mcp`, commit de `netbox-mcp-rw`, `strands-agents`, cEOS
  recommandée), et le port NetBox par défaut.
- Le détail des startup-configs cEOS (management, SSH, utilisateur) et la façon d'attendre que SSH soit prêt.
- TextFSM ou parsing maison pour `show vlan` ; le format exact du tableau d'audit.
- Les permissions NetBox précises des deux utilisateurs MCP.
- Le texte des skills et du system prompt, en partant de ceux de `strand_agents_lab`.
- Le journal (`[netbox: ...]`, `[netmiko: ...]`, `[guard: ...]`) : même esprit que l'agent existant.
- La mesure du coût d'une session de démo pour le README.

## Identité publique

- Repo : https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand (public). Le README commence par son
  `git clone`.
- Licence MIT, au nom du commanditaire. Décision du commanditaire.

## Environnement de construction et de test

Décision du commanditaire : le repo est construit et testé sur son Mac Apple Silicon, dans une VM Linux arm64 OrbStack,
avec l'image cEOS ARM (EFT). Conséquences pour le builder :

- Tout tourne dans la VM : Docker, Containerlab, NetBox, `uv`, `netmiko-mcp`, l'agent et la clé API. `install.sh` est
  lancé depuis la VM, dans un clone du repo qui y est monté ou cloné. Les leafs sont sur le bridge Containerlab interne
  à la VM ; rien n'a besoin d'être joignable depuis macOS, sauf l'interface NetBox pour la regarder (port publié par la
  VM).
- Le builder écrit un court runbook `docs/dev-macos.md` : créer la VM OrbStack, y installer Docker et Containerlab,
  poser l'image `cEOSarm-lab-*`, lancer `install.sh`. Ce n'est pas la cible du lecteur et le README le dit.
- Toute limite rencontrée avec l'image ARM (fonction absente, lenteur, message d'erreur) est notée dans ce runbook,
  pour que le lecteur x86_64 ne la prenne pas pour un bug du repo.
- Le script n'aura pas été exécuté sur un Ubuntu x86_64 propre avant publication. Le README l'annonce honnêtement
  (« tested on arm64 under OrbStack ; the x86_64 path is the documented target but has not been run by the author »)
  jusqu'à ce qu'une passe x86_64 ait lieu. Le coût d'une session mesuré dans le README vient de la VM ARM.

## Ce que le commanditaire doit encore trancher

Rien : les trois questions ouvertes (machine de test, licence, langue) ont été tranchées le 22 octobre 2026 et sont
reportées ci-dessus.

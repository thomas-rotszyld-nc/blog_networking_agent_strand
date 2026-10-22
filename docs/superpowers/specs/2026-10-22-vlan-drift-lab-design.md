# Lab « intention → déploiement » : un agent Strands entre Infrahub et des switchs Containerlab

Document de conception, 22 octobre 2026 (révision Infrahub, remplace la version NetBox du même jour). Repo compagnon
d'un article de blog sur Strands Agents (exploration). Le lecteur clone le repo, lance `install.sh`, suit l'article, et
voit un agent changer l'intention dans Infrahub, la faire relire, puis déployer la configuration générée sur de vrais
switchs et vérifier. L'article lui-même n'est pas dans ce repo.

## Intention et pourquoi

L'article veut montrer ce qu'un agent Strands apporte sur un cas réseau que tout ingénieur reconnaît, pas sur un jouet,
et le montrer avec Infrahub tel qu'Infrahub est conçu : la source de vérité ne décrit pas des lignes de configuration,
elle génère la configuration complète de chaque équipement à partir d'un modèle de données, dans des branches relues
par un humain. L'agent suit cette boucle au lieu de la contourner :

**intention → relecture → rendu → déploiement → vérification**

Un seul objet métier, la VLAN, traverse tout l'article, pour que le lecteur n'ait qu'un concept à suivre ; la complexité
est dans la mécanique de l'agent et d'Infrahub, c'est elle qu'on veut lui faire voir. Trois actes, le même agent recevant
un peu plus de pouvoir à chaque fois :

1. **Changer l'intention.** « Ajoute la VLAN 40 GUESTS au site lab et mets l'Ethernet3 des deux leafs dessus. » L'agent
   écrit dans Infrahub par le serveur MCP officiel, sur une branche de session créée pour lui, et ouvre une Proposed
   Change. L'utilisateur la relit dans l'interface d'Infrahub, y voit le diff des données et celui des configurations
   rendues, et fusionne. L'agent n'a rien touché de définitif.
2. **Déployer.** « Déploie la configuration des leafs. » L'agent récupère la configuration rendue par Infrahub pour
   chaque leaf, montre le diff avec la configuration en cours du switch, et la pousse en remplacement complet par un
   outil maison, après confirmation sur le terminal. Les gardes sont en code : refus si le rendu manque ou n'a pas son
   bloc de management, limite d'équipements par tour.
3. **Vérifier.** `show vlan` sur les deux leafs par le serveur MCP officiel de Netmiko, en lecture seule. Le même
   mécanisme sert à la dérive : si quelqu'un modifie un switch à la main, le diff rendu / en cours la fait apparaître
   et le remède est le même déploiement.

Ce que l'article montre de Strands, dans l'ordre d'apparition : `Agent` + `AnthropicModel`, outils MCP (`MCPClient`,
deux serveurs), skills (`AgentSkills`), outils maison (`@tool`), hooks (`BeforeToolCallEvent` pour confirmer,
`AfterToolCallEvent` pour tracer), steering (`SteeringHandler` + `LedgerProvider`).

Ce que l'article montre d'Infrahub : schéma chargé depuis la bibliothèque OpsMill, données en fichiers d'objets, dépôt
Git raccordé (requête GraphQL + template Jinja2 + définition d'artifact), branches et Proposed Change, artifacts rendus.

## Buts

- `sh install.sh` monte toute la pile sur une machine Linux propre, sans autre action que poser l'image cEOS, et se
  rejoue sans casser ce qui existe.
- Les switchs démarrent avec la configuration rendue par Infrahub : le diff initial entre rendu et en cours est vide.
- Un script séparé introduit une dérive sur un switch, rejouable, pour la variante « dérive » de l'acte 3.
- L'agent fonctionne tel quel avec le lecteur : `uv run python agent.py` puis les trois questions de l'article.
- Tout le code vu dans l'article vient de ce repo, sans adaptation : le template, la requête, l'agent, les gardes.
- Le README explique pourquoi Infrahub écrit par MCP sur une branche, pourquoi la lecture des switchs passe par
  `netmiko-mcp`, le serveur officiel de l'auteur de Netmiko, et pourquoi l'écriture passe par un outil maison.

## Non-buts

- Pas de fabric : deux leafs, pas de spine, pas de routage. Le template rend une configuration d'access switch.
- Pas de modélisation au-delà du nécessaire : site, équipements, interfaces, VLANs, adresse de management. Tout le
  reste de la configuration (comptes, API, spanning-tree) est du socle fixe dans le template.
- Pas de generators, de checks ni de transformations Python Infrahub : un seul template Jinja2, une seule requête.
- Pas de multi-agent, pas de mémoire, pas d'évaluation. Un agent, un terminal.
- Pas d'interface web côté agent. Le chat se fait dans le terminal.

## Anti-buts

- Un lecteur qui doit bricoler `install.sh` pour que ça marche. Si une étape ne peut pas être automatisée (l'image
  cEOS), le script la détecte, dit quoi faire, et s'arrête proprement.
- Un agent qui pousse autre chose que la configuration rendue par Infrahub : pas de commande à la main, pas de
  configuration éditée par le modèle. L'outil de déploiement ne prend pas de texte de configuration en entrée, il va le
  chercher lui-même dans Infrahub.
- Un déploiement qui coupe l'accès au switch : le rendu doit contenir le bloc de management attendu, sinon refus.
- Un agent qui écrit dans la branche par défaut d'Infrahub : le serveur MCP l'interdit par construction.
- Un repo qui porte des traces du lab interne (`strand_agents_lab`) : noms d'équipements, champs custom, utilisateurs,
  nom du projet Compose, tokens codés en dur, fuseau horaire, mots de passe. Le code en est inspiré, les données non.

## Contraintes

- **Infrahub** 1.11.9, par le Compose officiel (`https://infrahub.opsmill.io/1.11.9`, URL versionnée) : Neo4j,
  RabbitMQ, Redis, Postgres, Prefect, serveur, workers. La doc officielle demande 8 Go de RAM et 6 cœurs au minimum
  pour ce Compose, 16 Go recommandés ; avec deux cEOS, le README annonce 16 Go. Les images Infrahub et Neo4j existent
  en amd64 et arm64 (vérifié). Port 8000. Token admin initial fixé par `INFRAHUB_INITIAL_ADMIN_TOKEN`.
- **Schéma** : copies des fichiers de la bibliothèque OpsMill `opsmill/schema-library` au commit `26336e9026df` de la
  branche `main` (2026-10-09, CHANGELOG « v2.0.0 », aucun tag posé ; le tag `v1.4.11` a un modèle différent, sans
  `IpamVLANGroup` ni `location_site`), Apache 2.0, en-têtes conservés : `base/organization`, `base/location`,
  `base/dcim`, `base/ipam`, `extensions/location_site`, `extensions/vlan`. Chargées par `infrahubctl schema load`.
  Le README cite « schema-library v2.0.0 @ 26336e9026df ». `DcimPhysicalDevice.location` est obligatoire ;
  `InterfacePhysical` hérite aussi d'`InterfaceLayer3`, donc l'adresse de management peut être portée par
  `Management0`. Kinds utilisés : `OrganizationManufacturer`,
  `DcimPlatform`, `DcimDeviceType`, `LocationSite`, `DcimDevice`, `InterfacePhysical`, `IpamIPAddress`,
  `IpamVLANGroup`, `IpamVLAN`. `LocationSite` hérite de `IpamVLANGroupScope` : le groupe de VLANs est rattaché au site.
  `InterfacePhysical` hérite de `InterfaceLayer2` que l'extension `vlan` étend d'une relation `untagged_vlan`.
- **Données** : fichiers d'objets Infrahub (`apiVersion: infrahub.app/v1`, `kind: Object`), chargés par
  `infrahubctl object load`. Les relations vers un generic (scope du groupe, `untagged_vlan`) se déclarent par un bloc
  `kind` + `data` qui répète les champs obligatoires de la cible.
- **`infrahub-mcp`** 1.2.0 (PyPI, `uvx infrahub-mcp`), serveur officiel d'OpsMill, Apache 2.0. Outils utilisés :
  `get_schema`, `get_nodes`, `search_nodes`, `query_graphql` en lecture ; `node_upsert` (attributs scalaires
  seulement), `mutate_graphql` (relations), `propose_changes`, `get_session_info` en écriture. Toute écriture va sur la
  branche de session (`INFRAHUB_MCP_BRANCH_PATTERN`, ici `agent/{date}-{hex}`), créée paresseusement au premier
  write ; avant, `get_session_info` renvoie `session_branch: null`. La branche par défaut n'est atteignable que par
  Proposed Change fusionnée. `node_upsert` renvoie `id`, `display_label`, `branch` ; `propose_changes` renvoie `id`,
  `source_branch`, `destination_branch` ; `mutate_graphql` renvoie la réponse GraphQL brute, sans la branche : pour que
  le hook puisse lier un objet créé ainsi, la mutation demande `object { id }` et le hook relit la branche par
  `get_session_info`. Le serveur lit lui-même `INFRAHUB_ADDRESS` / `INFRAHUB_API_TOKEN` dans `./.env`
  (`INFRAHUB_MCP_ENV_FILE`). Il exige Python 3.13, que `uvx` fournit. Interface : `/objects/<Kind>/<id>?branch=<b>`
  et `/proposed-changes/<id>`.
- **Dépôt Git raccordé** : le repo compagnon lui-même, `https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand`,
  branche par défaut `main`, enregistré dans Infrahub en lecture seule (`infrahubctl repository add --read-only
  --ref main`), URL et ref surchargeables par `INFRAHUB_REPO_URL` / `INFRAHUB_REPO_REF` pour un fork ou une branche
  de développement. Un dépôt en lecture seule **ne suit pas les pushs** (règle du plugin `infrahub-skills`,
  vérifiée) : il importe à la création puis seulement sur demande, par la mutation
  `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})`. Le repo porte donc un `scripts/reimport.sh` qui l'appelle,
  et la boucle de développement est : push, reimport, attendre le re-rendu. **Un comportement reste à prouver** : la
  Proposed Change d'une branche de données créée par le MCP montre bien le diff des artifacts avec un dépôt en lecture
  seule. Le plan commence par un spike qui le vérifie dans la VM, avant tout template ; si c'est faux, repli sur un
  `CoreRepository` avec des identifiants GitHub, et le README change. Autres règles du plugin reprises : l'ordre
  d'installation est schéma, données, puis dépôt ; les fichiers d'objets ne déclarent jamais le dépôt lui-même ; la
  cible d'artifact doit hériter de `CoreArtifactTarget`, ce que `DcimDevice` fait déjà au commit épinglé ;
  l'appartenance au groupe se déclare côté membre (`member_of_groups`), le groupe étant créé avant. `.infrahub.yml` déclare une requête GraphQL, une
  transformation Jinja2 et une définition d'artifact ciblant le groupe `leafs`, paramètre `device: name__value`.
  Conséquence de développement : un changement de template ou de requête doit être poussé sur GitHub pour être rendu
  par Infrahub ; `infrahubctl render` permet de tester le rendu en local contre l'Infrahub qui tourne.
- **Artifacts** : un `CoreArtifact` par leaf, définition `leaf_startup_config`, contenu `text/plain`, lu par
  `GET /api/artifact/<id>` avec le token, ou par la voie du SDK (`node.artifact_fetch(name)`, qui lit
  `/api/storage/object/<storage_id>`). Rendu à l'import du dépôt, puis à chaque changement de données ou de
  template ; la Proposed Change montre le diff des artifacts. Si le rendu après fusion tarde, le builder peut le
  déclencher par `POST /api/artifact/generate/<definition id>`, qui ne fait que mettre en file : toute attente
  d'artifact interroge `CoreArtifact` jusqu'à `status == Ready` et `storage_id` présent, avec un délai maximal. Dans le
  template Jinja2, `data` est la réponse GraphQL brute, chaque attribut se lit `.value` ; seul un sous-ensemble de
  filtres Jinja2 est autorisé. Le template est testé hors ligne par le cadre de tests du SDK (`tests/test_transforms.yml`,
  `jinja2-transform-unit-render`, fixtures `input.json` / `output.txt`, lancé par `pytest`).
- **`netmiko-mcp`** 0.2.0 (PyPI), lecture seule, liste blanche `show vlan*` et `show running-config*`, inventaire
  `.netmiko.yml` partagé avec les outils maison, journal d'audit dans le repo (`audit_log_file`). Au-delà de
  `save_threshold` (1000 lignes) la sortie part dans un fichier au lieu de revenir au modèle ; le `show running-config`
  d'un cEOS reste en dessous.
- **Containerlab** et **cEOS** : comme avant. Image à poser dans `images/` (`cEOS64-lab-*`, `cEOS-lab-*` ou
  `cEOSarm-lab-*`), taguée `ceos:lab`. Lab `vlan-lab`, leafs `leaf1`/`leaf2`, management `172.20.20.11`/`.12`,
  `admin`/`admin`. Les startup-configs sont les artifacts téléchargés, pas des fichiers écrits à la main.
- **Déploiement sur EOS** : remplacement complet, atomique. Voie recommandée : session de configuration
  (`configure session`, `rollback clean-config`, les lignes du rendu, `commit`) puis `write memory`, par Netmiko
  `arista_eos`. Voie de repli si cEOS refuse : transfert du fichier et `configure replace`. Le builder tranche en
  essayant, et l'outil vérifie que SSH répond encore après le commit.
- **Clé API Anthropic** dans l'environnement du lecteur. Le README donne un ordre de grandeur du coût d'une session,
  mesuré lors des tests.
- Repo public, en anglais (code, README, skills, system prompt), licence MIT ; l'article en français traduit ce qu'il
  cite. Décisions du commanditaire.

## Le scénario, précisément

### Décor

Infrahub connaît un site `lab`, deux switchs d'accès Arista `leaf1` et `leaf2` (type `cEOS-lab`, plateforme
`Arista EOS`, rôle `leaf`, adresse de management sur `Management0`), un groupe de VLANs `lab-vlans` rattaché au site, et
trois VLANs :

| VID | Nom   |
|-----|-------|
| 10  | USERS |
| 20  | VOICE |
| 30  | IOT   |

Chaque leaf a trois ports d'accès `Ethernet1`, `Ethernet2`, `Ethernet3` (`l2_mode: access`, `untagged_vlan` sur 10, 20
et 30). Un groupe `leafs` contient les deux équipements : c'est la cible de la définition d'artifact.

Le template `eos_leaf.j2` rend, pour un leaf : hostname, utilisateur admin, les VLANs du site, les interfaces avec leur
description et leur VLAN d'accès, `Management0` avec son adresse, les API de management, `end`. Les parties qui bougent
viennent de la requête GraphQL (`leaf_config.gql`, variable `$device`) ; le socle est dans le template. `install.sh`
télécharge les deux artifacts et les donne à Containerlab comme startup-configs.

### Acte 1 : changer l'intention

Question : « Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it. »

Le skill `infrahub-change` donne la procédure : créer la VLAN par `mutate_graphql` (la relation `vlan_group` ne passe
pas par `node_upsert` ; la mutation demande `object { id }`) ; `get_session_info` pour connaître la branche, qui
n'existe qu'à partir de ce premier write ; mettre à jour les deux interfaces par `mutate_graphql` (`untagged_vlan` par
HFID, `["GUESTS"]`) ; relire par `get_nodes` sur la branche ; `propose_changes` avec un titre et une description qui
résument le changement ; donner à l'utilisateur le lien de la Proposed Change et s'arrêter là.
Le hook `ShowInfrahubLinks` imprime sur le terminal, après chaque écriture, la branche et le lien de l'objet ou de la
Proposed Change. Pas de confirmation avant les écritures Infrahub : la branche est le filet, et c'est le point de
l'acte. L'utilisateur fusionne dans l'interface, où il voit le diff des données et celui des deux configurations
rendues.

### Acte 2 : déployer

Question : « Deploy the configuration of the leafs. »

Le skill `deploy-config` donne la procédure : pour chaque leaf, `preview_config(device)` puis, si le diff n'est pas
vide, `deploy_config(device)` ; rendre compte ; ne jamais pousser de texte de configuration par un autre moyen.

- `preview_config(device) -> str` (outil maison, lecture seule, pas de confirmation) : va chercher l'artifact du leaf
  dans Infrahub (branche par défaut), lit la configuration en cours par Netmiko, renvoie un diff unifié, ou « no
  difference ». L'agent le montre à l'utilisateur.
- `deploy_config(device) -> str` (outil maison, écriture) : va chercher le même artifact et le pousse en remplacement
  complet. Trois choses se passent avant, dans cet ordre, et l'article les montre dans cet ordre :
  1. **Steering** (`DeployGuard`) : refuse si l'artifact manque ou est vide, si le rendu n'a pas `hostname <device>`,
     pas de bloc `interface Management0` avec l'adresse connue de l'inventaire, pas d'utilisateur `admin` ; refuse au
     delà de `max_devices` (2) équipements déployés dans le tour. La raison revient au modèle avec l'instruction de la
     rapporter plutôt que de réessayer.
  2. **Hook de confirmation** (`ConfirmDeploy`, `BeforeToolCallEvent`, après le steering) : affiche l'équipement et
     le diff, attend un `y`. Sans terminal, refuse.
  3. **L'outil** : session de configuration EOS, commit, `write memory`, puis vérifie que SSH répond encore et que
     `show running-config` contient la nouvelle VLAN ; renvoie un compte rendu.

Résultat attendu : les deux leafs portent la VLAN 40 et `Ethernet3` est dessus ; le diff de `preview_config` est vide
ensuite.

### Acte 3 : vérifier, et la dérive

Question : « Check the VLANs on both leafs. » L'agent lance `show vlan` par `send_show_command` (TextFSM) et rend un
tableau par leaf. Puis l'utilisateur lance `sh drift.sh` : sur leaf2, la VLAN 20 est renommée `VOIP` et une VLAN 99
`LEGACY` apparaît. « Is leaf2 still compliant? » → `preview_config(leaf2)` montre le diff ; « Fix it » → le même
déploiement qu'à l'acte 2 remet leaf2 d'équerre. Morale : la configuration n'a qu'une source, et l'agent ne fait que
la réappliquer.

## Ce que `install.sh` fait

Un seul point d'entrée, idempotent, étapes numérotées, checks à la fin, sortie non nulle au premier problème.

0. **Prérequis**, tous vérifiés avant de sortir : Docker + Compose v2 sans `sudo`, `containerlab`, `uv`, `git`,
   `curl`, une archive cEOS dans `images/`, au moins 16 Go de RAM (avertissement, pas blocage). `sudo` n'est utilisé que
   pour Containerlab.
1. **`.env`** : conserve ou génère `INFRAHUB_API_TOKEN` (= `INFRAHUB_INITIAL_ADMIN_TOKEN`, UUID),
   `INFRAHUB_INITIAL_AGENT_TOKEN` (UUID) et `INFRAHUB_SECURITY_SECRET_KEY`, pour ne pas publier un Infrahub aux
   secrets par défaut connus ; écrit `INFRAHUB_ADDRESS`, `INFRAHUB_REPO_URL` (défaut : le repo public),
   `INFRAHUB_REPO_REF` (défaut `main`) ; conserve `ANTHROPIC_API_KEY`.
2. **Infrahub** : télécharge le Compose versionné dans `infrahub/docker-compose.yml` s'il manque, `docker compose -p
   vlan-lab up -d` (le fichier n'a pas de `name:`), attend `GET /api/config`, le point de santé du serveur
   (plusieurs minutes au premier démarrage).
3. **Schéma** : `infrahubctl schema load infrahub/schema --wait 60` (`infrahubctl` par `uvx --from infrahub-sdk[ctl]`,
   version épinglée).
4. **Données** : `infrahubctl object load infrahub/objects` ; création du groupe `leafs` avec ses deux membres (fichier
   d'objets si le chargeur l'accepte, sinon une mutation GraphQL).
5. **Dépôt** : `infrahubctl repository add blog-lab $INFRAHUB_REPO_URL --read-only --ref $INFRAHUB_REPO_REF` s'il
   n'existe pas ; attente de l'import et des deux artifacts (`CoreArtifact` de la définition `leaf_startup_config` pour
   `leaf1` et `leaf2`) ; téléchargement dans `clab/generated/leaf1.cfg` et `leaf2.cfg`.
6. **`netmiko-mcp`** : `uv tool install netmiko-mcp==0.2.0` ; génération de `netmiko/netmiko-mcp.yml`, `.netmiko.yml`
   (leaf1, leaf2, groupe `leafs`), `commands.yml` (`show vlan*`, `show running-config*`).
7. **Containerlab** : `docker import` vers `ceos:lab` si besoin ; `sudo containerlab deploy --reconfigure` avec les
   startup-configs générées ; attente de SSH sur les deux leafs.
8. **Agent** : `uv sync` ; `uv run python agent.py --list-tools` doit lister les outils des deux MCP et les deux outils
   maison.
9. **Checks** : trois VLANs sur le site dans Infrahub ; deux artifacts non vides ; `show vlan` de chaque leaf contient
   `USERS`, `VOICE`, `IOT` ; `preview_config` des deux leafs renvoie « no difference ».

`drift.sh` modifie leaf2 à la main (et `--reset` redéploie Containerlab avec les artifacts). `uninstall.sh` détruit la
topologie et arrête Infrahub (`--purge` efface les données), garde images et `.env`.

## Structure du repo

```
README.md  LICENSE  .infrahub.yml                   .infrahub.yml : ce qu'Infrahub lit quand il clone ce repo
install.sh  drift.sh  uninstall.sh
infrahub/docker-compose.yml                         téléchargé par install.sh (git-ignoré), version épinglée
infrahub/schema/*.yml                               copies de schema-library v1.4.11, en-têtes conservés
infrahub/objects/*.yml                              site, groupe de VLANs, VLANs, constructeur, plateforme, type, leafs
infrahub/queries/leaf_config.gql                    la requête de la transformation
infrahub/templates/eos_leaf.j2                      le template de configuration d'un leaf
clab/vlan-lab.clab.yml  clab/generated/             la topologie ; les startup-configs téléchargées (git-ignorées)
scripts/reimport.sh                                 fait avancer le dépôt en lecture seule après un push
tests/test_transforms.yml  tests/fixtures/           tests hors ligne du template (cadre de tests du SDK) et pytest
netmiko/                                            généré par install.sh (git-ignoré)
images/                                             l'archive cEOS posée par le lecteur (git-ignoré)
agent.py                                            l'agent : modèle, MCP, skills, outils maison, hooks, steering, chat
vlanlab/infrahub_tools.py                           fetch_artifact, preview_config, deploy_config, ShowInfrahubLinks
vlanlab/guards.py                                   DeployGuard (steering), ConfirmDeploy (hook)
vlanlab/eos.py                                      Netmiko : running-config, remplacement par session, inventaire
skills/infrahub-change/SKILL.md  skills/deploy-config/SKILL.md  skills/vlan-check/SKILL.md
.mcp.json  .env.example  pyproject.toml  uv.lock
docs/superpowers/specs/  docs/superpowers/plans/  docs/dev-macos.md
```

Le découpage suit l'ordre de lecture de l'article : un fichier par section. Le builder peut regrouper si des fichiers
deviennent trop petits pour mériter d'exister.

## Décisions prises ici (à contester, pas à redécouvrir)

- **Infrahub plutôt que NetBox**, et le scénario suit la boucle d'Infrahub (configuration générée, branches,
  Proposed Change) plutôt que des commandes poussées à la main. Décision du commanditaire.
- **Le repo compagnon est le dépôt Git d'Infrahub.** Il est public, Infrahub le clone en lecture seule, rien d'autre à
  héberger. Un lecteur qui forke change `INFRAHUB_REPO_URL`.
- **Schéma et données chargés par `infrahubctl`**, pas par `.infrahub.yml` (qui le permettrait) : la boucle de
  développement sur les données ne passe pas par GitHub, et `.infrahub.yml` ne porte que le rendu.
- **Un template, socle fixe dedans** : seuls VLANs, interfaces et adresse de management viennent des données. Validé
  avec le commanditaire.
- **Deux outils maison** : `preview_config` sans confirmation, `deploy_config` gardé. Aucun ne prend de texte de
  configuration en entrée.
- **Pas de confirmation sur les écritures Infrahub** : la branche et la Proposed Change jouent ce rôle, et c'est ce que
  l'acte 1 veut montrer. Le hook ne fait qu'afficher les liens.
- **cEOS** plutôt que SR Linux ; **deux leafs** ; **`netmiko-mcp`** en lecture ; **outil maison** en écriture ; **même
  inventaire** `.netmiko.yml` pour les deux : décisions reprises de la version précédente.
- **`netmiko-mcp` 0.2.0** depuis PyPI, pas un commit Git.
- **Même modèle Anthropic** que l'agent de `strand_agents_lab`, par `AnthropicModel`.

## Laissé au builder

- Les versions exactes à épingler (`infrahub-sdk[ctl]` 1.23.2 au moment d'écrire, `strands-agents` ≥ 1.61.1, cEOS
  recommandée), le nom de branche de session, la forme exacte du diff.
- Le détail du template et de la requête ; le nom du champ d'adresse de management dans le schéma (`primary_address`
  ou l'adresse de `Management0`) ; la forme des fichiers d'objets pour les relations vers un generic.
- La façon d'attendre l'import du dépôt et le rendu des artifacts (toujours en interrogeant `CoreArtifact` jusqu'à
  `Ready`), et si le rendu après fusion doit être déclenché.
- La mécanique exacte du remplacement de configuration sur cEOS (session + commit, ou transfert + replace).
- Le texte des skills et du system prompt, en partant de ceux de `strand_agents_lab`.
- Le journal (`[infrahub: ...]`, `[tool: ...]`, `[guard: ...]`) : même esprit que l'agent existant.
- La mesure du coût d'une session de démo pour le README.

## Environnement de construction et de test

Décision du commanditaire : le repo est construit et testé sur son Mac Apple Silicon, dans une VM Linux arm64 OrbStack,
avec l'image cEOS ARM (EFT). Conséquences :

- La VM a au moins 16 Go de RAM et 6 cœurs (Infrahub 8 Go minimum, deux cEOS, le reste). Tout tourne dans la VM :
  Docker, Containerlab, Infrahub, `uv`, les MCP, l'agent, la clé API. `install.sh` est lancé depuis la VM. Rien n'a
  besoin d'être joignable depuis macOS sauf l'interface d'Infrahub (port 8000 publié par la VM) pour relire et
  fusionner la Proposed Change.
- Pendant le développement, Infrahub clone le repo depuis GitHub : les templates et requêtes se testent en local par
  `infrahubctl render`, puis se poussent sur une branche de développement enregistrée par `INFRAHUB_REPO_REF`.
- Un court runbook `docs/dev-macos.md` : créer la VM, y installer Docker, Containerlab, uv, git ; poser l'image
  `cEOSarm-lab-*` ; lancer `install.sh` ; les limites rencontrées avec l'image ARM, chacune avec son contournement.
- Le script n'aura pas été exécuté sur un Ubuntu x86_64 propre avant publication. Le README l'annonce honnêtement
  jusqu'à ce qu'une passe x86_64 ait lieu. Le coût d'une session mesuré dans le README vient de la VM ARM.

## Ce que le commanditaire doit encore trancher

Rien : machine de test, licence, langue, choix d'Infrahub, découpage du template et entrée par un changement
d'intention ont été tranchés le 22 octobre 2026.

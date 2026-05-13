# CommieBot

### Requirements
[Discord Developer Account](https://discord.com/developers/applications)

[Bot Token](https://docs.discord.com/developers/quick-start/getting-started)

[docker / docker compose](https://docs.docker.com/engine/install/ubuntu/)
```bash
# Easy Docker Install on Linux/(maybe MacOS) machines:
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh ./get-docker.sh
```
### Deployment
1. `.env` file: `DISCORD_TOKEN=your_token`
2. `docker compose up -d --build`

### Commands

**Mutual Aid**
* `/aidrole` <role>
* `/requestaid` <amount> <description>
* `/sendaid` <aid_id> <amount> [anonymous]
* `/listaids`
* `/deleteaid` <aid_id>
* `/clearaids`

**Ticketing**
* `/mod ping` <description>
* `/mod ticket staff_add` <role>
* `/mod ticket staff_remove` <role>
* `/mod ticket staff_list`
* `/mod ticket list`
* `/mod ticket add` <user>
* `/mod ticket close`

**Commie Resource Planning (CRP)**
* `/crp committee create` <name> [description]
* `/crp committee edit` <old_name> <new_name>
* `/crp committee remove` <name>
* `/crp committee list`
* `/crp role assign` <target> <role> [committee_name]
* `/crp role remove` <target> <role> [committee_name]
* `/crp role view` [target]
* `/crp role list` <committee_name>
* `/crp role listall`

**Quotes**
* `/quoteuser` <user> <quote> [layout]
* `/quoteadd` <name> <photo>
* `/quotelist`
* `/quotegen` <name> <quote> [layout]
* `/quotedelete` <name>

**Attendance (WIP)**
* `/attendance` <event_id>


```


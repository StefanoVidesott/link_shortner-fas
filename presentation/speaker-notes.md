# Note per il Presentatore
### Link Shortener — FAS UniTN · A.A. 2025/2026
> Durata target: ~35 minuti · Presentatori: Stefano Videsott, Ismaele De Giorgi

---

## Slide 1 — Cover

Buongiorno a tutti. Oggi vi presentiamo il secondo progetto per il corso di
Fondamenti di Amministrazione di Sistema. Il progetto si chiama **Link
Shortener**, e il nome descrive la funzionalità principale dell'applicazione —
un servizio per accorciare URL lunghi. Ma come vedete dai badge in basso,
l'applicazione in sé è solo una piccola parte di quello che abbiamo costruito:
l'obiettivo del corso era la **infrastruttura** che la circonda, e questo è il
focus della nostra presentazione.

---

## Slide 2 — Indice

*(click per ogni voce)* La presentazione si articola in sei sezioni. Partiremo
dal progetto e dalle sue funzionalità, poi vedremo l'architettura complessiva
del sistema. La parte più consistente è dedicata all'**osservabilità** —
metriche con Prometheus, dashboard Grafana, e aggregazione dei log con Loki. Poi
vedremo il **deployment automatico** con GitHub Actions e Ansible. Concluderemo
con una demo live e le nostre riflessioni finali.

---

## Slide 3 — Sezione: 01 · Il Progetto

*(slide di transizione, nessun testo da leggere — pausa breve)*

---

## Slide 4 — Il Progetto

*(click per ogni card)* Il progetto nasce da un'idea semplice: un **URL
shortener self-hosted**. L'utente incolla un link lungo, l'applicazione
restituisce un codice breve a sei caratteri, e chiunque usi quel codice viene
reindirizzato all'URL originale.

Abbiamo poi costruito attorno a questa applicazione uno **stack di osservabilità
completo**: ogni richiesta viene misurata, ogni log viene aggregato e reso
ricercabile, e gli errori vengono catturati automaticamente.

Infine, tutto il deployment è **automatizzato e riproducibile**: un `git push`
porta il codice in produzione senza intervento manuale, e un singolo comando
Ansible configura un server partendo da zero.

*(click sull'ultima card)* E questa è proprio la chiave di lettura che ci ha
dato il corso: non è importante che l'applicazione sia complessa, è importante
che l'**infrastruttura** che la ospita sia solida, monitorata e gestibile.

---

## Slide 5 — API & Funzionalità

*(click per ogni endpoint)* L'applicazione espone cinque endpoint principali. Il
`POST /shorten` riceve un JSON con l'URL e restituisce il codice corto. Il `GET
/<code>` esegue il redirect — è l'endpoint più usato in produzione. Il `GET
/stats/<code>` permette di vedere quante volte un link è stato cliccato e quando
scade.

Gli ultimi due sono fondamentali per l'infrastruttura: `/health` viene usato dai
container orchestrator per sapere se l'applicazione è viva e connessa al
database, e `/metrics` espone tutte le metriche nel formato che Prometheus si
aspetta.

*(click sulle features)* Qualche dettaglio tecnico: i codici usano
`[A-Za-z0-9]`, sei caratteri, il che dà circa cinquantasei miliardi di
combinazioni possibili — più che sufficiente. Il TTL di default è trenta giorni,
configurabile via variabile d'ambiente. C'è un job in background che gira ogni
dieci minuti a fare pulizia dei link scaduti — e questa è una delle cose che
monitoriamo.

---

## Slide 6 — Sezione: 02 · Architettura & Stack

*(slide di transizione)*

---

## Slide 7 — Architettura di Sistema

Questo è il cuore del sistema. Il diagramma mostra come comunicano tutti i
componenti.

A sinistra abbiamo i due attori esterni: l'**utente** che usa l'applicazione via
browser sulla porta 5001, e **GitHub** che innesca il CI/CD ogni volta che
facciamo un push.

Al centro c'è il **Docker Network**, una rete bridge isolata che contiene tutti
i container. L'applicazione è composta da Flask e MySQL. Il gruppo osservabilità
contiene Prometheus, Promtail, Loki e Grafana — ne parleremo in dettaglio.

Alcune frecce da notare: Flask espone `/metrics` e Prometheus la **interroga**
attivamente ogni quindici secondi — è un modello pull, non push. I log invece
vengono **spinti**: Flask scrive su stdout in formato JSON, Promtail li
raccoglie dal socket Docker e li manda a Loki.

La freccia tratteggiata verso **Sentry** è intenzionalmente diversa: Sentry è un
servizio cloud esterno, non gira nel nostro Docker network. È opzionale — se non
si configura il DSN nel `.env`, l'integrazione rimane silenziosamente
disabilitata.

In basso a destra c'è il **GitHub Actions Runner**, che gira direttamente sul
server Arch Linux. Quando GitHub invia il trigger, il runner esegue il workflow
e aggiorna il Docker Compose.

---

## Slide 8 — Stack Tecnologico

*(click per ogni card)* Vediamo brevemente ogni tecnologia. **Flask** è il
framework Python per l'applicazione — minimale, senza overhead. Abbiamo aggiunto
`python-json-logger` per produrre log strutturati in JSON invece di testo
libero.

**MySQL 8** come database relazionale, con i dati su un named Docker volume —
dettaglio importante, ci torniamo nella parte CI/CD.

**Docker Compose** per orchestrare otto servizi con un unico file
dichiarativo. Tutti sullo stesso bridge network, comunicano per hostname.

**Prometheus** per le metriche — scraping ogni quindici secondi, cinque metriche
custom esposte dall'applicazione.

**Grafana** per la visualizzazione — con auto-provisioning della dashboard, zero
configurazione manuale al primo avvio.

**Loki e Promtail** insieme formano la pipeline di log — Promtail raccoglie,
Loki aggrega e indica, Grafana interroga.

**Sentry** per il tracciamento degli errori, cloud-based, opzionale.

**Ansible** per l'infrastruttura come codice — tre play, deployment su Arch
Linux completamente automatizzato.

---

## Slide 9 — Sezione: 03 · Osservabilità

*(slide di transizione)*

---

## Slide 10 — Metriche — Prometheus

*(click per ogni metrica)* Abbiamo definito cinque metriche custom
nell'applicazione Flask.

Le prime due coprono il **traffico HTTP**: `http_requests_total` è un Counter
che conta tutte le richieste ricevute, etichettate per metodo, endpoint e status
code. `http_request_duration_seconds` è un Histogram che registra quanto tempo
ha impiegato ogni richiesta — ci permette di calcolare i percentili P50, P95 e
P99.

Le due metriche sui link sono **metriche di business**: quanti link sono stati
creati e quanti redirect sono stati serviti dall'avvio dell'applicazione.

L'ultima è la più interessante dal punto di vista operativo:
`last_cleanup_success_timestamp` è un Gauge che registra il timestamp
dell'ultima esecuzione riuscita del job di pulizia. Ci dice se il worker sta
girando regolarmente.

*(click sulla nota)* Lato Prometheus, la configurazione di scraping è nel file
`prometheus.yml`. Notate che i target usano `flask:5000` e `grafana:3000` — le
**porte interne del container** nella bridge network — non le porte esposte
sull'host. Questo è un errore frequente: cambiando la porta host non cambia la
porta su cui il servizio è effettivamente in ascolto.

---

## Slide 11 — Dashboard Grafana

*(click per ogni panel)* La dashboard Grafana raccoglie sei panel che
corrispondono alle metriche che abbiamo definito.

Il **Request Rate** mostra il traffico in tempo reale, aggregato per endpoint —
utile per capire quale route è la più usata.

La **Latenza P50/P95/P99** è forse il panel più importante per la qualità del
servizio: il percentile 95 ci dice che il 95% delle richieste risponde entro un
certo tempo, isolando le "code lente" che la media nasconderebbe.

Il **Tasso Errori 5xx** filtra solo le risposte con status 500 o superiori — un
picco qui significa un bug o un problema di infrastruttura.

I panel su **Link Creati** e **Redirect** sono metriche di business: ci dicono
se il servizio viene usato e quanto.

Il **Cleanup Heartbeat** visualizza da quanto tempo non gira il job di pulizia —
se smette di aggiornarsi, c'è qualcosa che non va nel background scheduler.

*(click sulla nota)* Importante: la dashboard è **auto-provisioned**. Abbiamo
incluso il JSON della dashboard nel repository sotto
`grafana/provisioning/dashboards/`. Grafana la carica automaticamente all'avvio
— non serve aprire l'interfaccia e importarla a mano.

---

## Slide 12 — Query PromQL — Traffico

Queste sono le query PromQL che abbiamo usato per il pannello Traffico in
Grafana. Le mostriamo anche come riferimento per eventuali query manuali in
Prometheus.

`rate(http_requests_total[5m])` calcola quante richieste al secondo arrivano in
media negli ultimi cinque minuti. Con Grafana si può aggiungere un filtro per
endpoint o status per vedere la distribuzione.

La seconda query isola solo gli errori: `http_status=~"5.."` usa una regex — il
`=~` in PromQL. Il punto e i due punti catturano qualsiasi codice che inizia con
5.

La terza usa `sum by (endpoint)` per aggregare il totale storico raggruppando
per route — utile per vedere quali endpoint hanno ricevuto più traffico in
assoluto dall'avvio.

*(click sulle note)* Una cosa pratica: per le dashboard conviene usare `[5m]`,
per alert più reattivi si può scendere a `[1m]`, ma aumenta il rumore.

---

## Slide 13 — Query PromQL — Latenza

La latenza media si calcola dividendo la somma delle durate per il conteggio
delle richieste. È intuitiva, ma **nasconde le code**: se il 99% delle richieste
è velocissimo e l'1% impiega dieci secondi, la media sarà bassa e il problema
invisibile.

Per questo i **percentili** sono lo strumento
corretto. `histogram_quantile(0.95, ...)` usa le bucket che Prometheus registra
automaticamente per ogni Histogram. Il `le` nei label significa "less than or
equal" — Prometheus salva automaticamente quante richieste rientrano in ogni
bucket di tempo.

La terza query aggiunge `by (le, endpoint)` per separare i percentili per route
— possiamo vedere se `/shorten` è più lento di `/<code>`, per esempio.

*(click)* Basta cambiare `0.99` in `0.50` per la mediana, o `0.95` per il P95 —
la struttura della query rimane identica.

---

## Slide 14 — Query PromQL — Link

Queste tre query coprono le metriche di business dell'applicazione.

`rate(links_created_total[5m])` e `rate(links_redirected_total[5m])` mostrano la
velocità attuale — quanti link al secondo vengono creati e quante volte vengono
usati.

`links_created_total` senza `rate()` restituisce il valore cumulativo dall'avvio
— utile in una stat box per "totale link creati".

*(click)* Un rapporto interessante: se dividiamo il rate dei redirect per il
rate dei link creati, otteniamo una stima di quante volte viene usato ogni link
— una sorta di "tasso di utilizzo" del servizio.

---

## Slide 15 — Query PromQL — Worker di pulizia

Questa è probabilmente la metrica più sottile che abbiamo implementato, e anche
la più utile operativamente.

`time() - last_cleanup_success_timestamp_seconds` non misura un valore diretto,
ma **il tempo trascorso dall'ultimo successo**. Se il job gira ogni dieci
minuti, questo valore dovrebbe stare sempre sotto i 600 secondi. Se supera 1800
— trenta minuti — significa che il worker ha saltato almeno tre cicli,
probabilmente bloccato o crashato silenziosamente.

*(click)* Questo è il pattern **Deadman Switch**: invece di rilevare un errore
attivo, rileviamo l'**assenza di un segnale atteso**. È lo stesso principio
usato in produzione per monitorare job batch, cron, e qualsiasi processo che
"batte" a intervalli regolari.

Senza questa metrica, il Background Scheduler potrebbe bloccarsi e noi non lo
scopriremmo mai — i link scaduti si accumulerebbero nel database senza che
nessun errore venga loggato.

---

## Slide 16 — Log Strutturati — Loki

Parliamo ora della pipeline dei log.

Flask scrive ogni richiesta HTTP su `stdout` in **formato JSON strutturato**,
grazie alla libreria `python-json-logger`. Non testo libero, ma un oggetto JSON
con campi ben definiti: timestamp, livello, messaggio, metodo HTTP, path, status
code.

Promtail si connette al **Docker socket** e scopre automaticamente i container
in esecuzione. Filtra solo il container Flask, applica una pipeline di
trasformazione in tre fasi: prima estrae i campi dal JSON, poi promuove il campo
`level` a **label Loki** indicizzato, infine scarta i log `GET /health 200`.

*(click)* Perché scartare i log di health check? Sono rumore: vengono generati
ogni pochi secondi dal container orchestrator, non portano informazioni utili, e
aumentano il costo di storage. Le informazioni sull'uptime le abbiamo già in
Prometheus tramite `/metrics`.

Il motivo per cui solo `level` diventa un label indicizzato è la
**cardinalità**: se indicizzassimo anche `method`, `path` o `status_code`
avremmo migliaia di combinazioni di label, e Loki degrada drasticamente in
performance con alta cardinalità. I campi ad alta cardinalità si lasciano come
metadata JSON e si filtrano a query time con `| json | path="/shorten"`.

*(click)* Le query LogQL in Grafana sono semplici ma potenti. `{job="flask",
level="ERROR"}` restituisce istantaneamente tutti gli errori perché `level` è
indicizzato. Aggiungendo `| json` dopo, si possono filtrare su qualsiasi campo
del log.

---

## Slide 17 — Error Tracking — Sentry

Sentry copre un caso d'uso che né Prometheus né Loki gestiscono bene: il **debug
approfondito delle eccezioni**.

L'integrazione è opzionale e completamente non invasiva: se la variabile
d'ambiente `SENTRY_DSN` non è impostata nel `.env`, il blocco `if _sentry_dsn`
non viene eseguito e l'import di sentry_sdk non avviene. Zero overhead.

*(click)* Quando è attivo, Sentry cattura automaticamente ogni eccezione non
gestita con lo **stack trace completo**, i valori delle variabili locali, la
request HTTP che ha causato l'errore, e il contesto Flask.

Il `traces_sample_rate=0.1` significa che traccia il dieci percento delle
transazioni per il performance monitoring — abbastanza per avere dati statistici
senza un impatto significativo sul carico.

*(click)* La distinzione rispetto a Loki: Loki ci dice "ci sono stati 47 errori
500 nell'ultima ora". Sentry ci dice "questo specifico errore si è verificato in
questo file alla riga 83, con questo valore di input, e questo è lo stack
trace". Sono strumenti complementari, non alternativi.

---

## Slide 18 — Sezione: 04 · CI/CD & Deployment

*(slide di transizione)*

---

## Slide 19 — GitHub Actions — CI/CD

Vediamo il workflow di CI/CD. *(scorrere le highlight del codice con i click)*

Si attiva su ogni `push` al branch `main`, oppure manualmente via
`workflow_dispatch` — utile per forzare un re-deploy senza fare un commit.

Il job usa `runs-on: self-hosted` — non un runner cloud di GitHub, ma il
**runner installato direttamente sul nostro server Arch Linux**. Questo
significa che il deploy avviene localmente, senza SSH in ingresso dall'esterno.

Il primo step è `actions/checkout@v4`, che clona il repository nella directory
di lavoro del runner. Questo è equivalente a un `git fetch` + `git reset --hard`
sul commit che ha triggerato il workflow — non serve un `git pull` separato.

Il secondo step copia il file `.env` da un percorso stabile sul server nella
directory di lavoro. Il `.env` non è nel repository per ovvie ragioni di
sicurezza — vive sul server e viene copiato all'occorrenza.

Poi `docker compose build` ricostruisce l'immagine Flask se il codice è
cambiato, e `docker compose up -d --remove-orphans` aggiorna i container in
esecuzione, rimuovendo quelli obsoleti.

Infine un health check su `/health` verifica che l'applicazione sia partita
correttamente e sia connessa al database.

*(click per ogni card)* Sul runner self-hosted: gira come servizio systemd sotto
l'utente `deploy`, che è nel gruppo `docker` — quindi può eseguire comandi
Docker senza sudo. Si registra a GitHub via API usando un token temporaneo
ottenuto durante il provisioning Ansible. Non richiede porte aperte in ingresso
— è il runner che contatta GitHub outbound, quindi funziona anche dietro NAT.

---

## Slide 20 — Ansible — Infrastructure as Code

L'intero provisioning del server è descritto in un **Ansible playbook** composto
da tre Play con responsabilità separate.

*(click)* Il **Play 1** esegue il setup di sistema: installa Docker, Git e UFW,
abilita il servizio Docker, crea l'utente `deploy`, autorizza la chiave SSH
pubblica, e configura il firewall aprendo solo le porte 22, 80 e 443.

*(click)* Il **Play 2** gestisce il deploy dell'applicazione: clona o aggiorna
il repository, crea il file `.env` dal template se non esiste — e in quel caso
si ferma chiedendo all'operatore di configurarlo. Una volta configurato, fa il
pull delle immagini e porta su lo stack con `docker compose up`.

*(click)* Il **Play 3** installa il GitHub Actions runner: scarica il binario,
ottiene il token di registrazione direttamente dall'API GitHub usando un
Personal Access Token, configura il runner in modalità non interattiva, e lo
installa come servizio systemd.

*(click)* Tre proprietà importanti del playbook: è **idempotente** — possiamo
rieseguirlo in qualsiasi momento senza effetti collaterali, aggiorna solo quello
che è cambiato. Ha una **separazione chiara** di responsabilità — ogni Play ha
il suo scope. E gestisce i **segreti in modo sicuro** — `vars.yml` è gitignored,
il `.env` non esce mai dal server.

---

## Slide 21 — Sezione: 05 · Demo Live

*(slide di transizione)*

---

## Slide 22 — Demo

Adesso passiamo alla parte pratica. Faremo una demo in tre parti.

**Prima:** mostreremo l'applicazione — accorceremo un link, lo useremo, vedremo
le statistiche e il pannello admin.

**Seconda:** apriremo Grafana e vedremo le metriche muoversi in tempo reale
mentre generiamo traffico. Mostreremo la latenza, il rate di richieste, e
cercheremo i log nella sezione Explore.

**Terza:** faremo un commit e un push, e mostreremo il workflow GitHub Actions
che gira automaticamente, con il runner che esegue il deploy sul server.

I riferimenti di rete: l'app è sulla porta 5001, Grafana sulla 5002, Prometheus
sulla 5003.

---

## Slide 23 — Screenshot · Applicazione

*(mostrate lo screenshot dell'applicazione — o passate direttamente alla demo
live)*

Questa è la home page dell'applicazione. L'interfaccia è volutamente minimale:
un campo di input per l'URL e un pulsante. Il risultato è il link accorciato con
il dominio configurato nel `.env`.

---

## Slide 24 — Screenshot · Dashboard Grafana

*(mostrate lo screenshot della dashboard — o passate direttamente alla demo
live)*

Questa è la dashboard Grafana auto-provisioned. Potete vedere i sei panel che
abbiamo descritto — request rate, latenza con percentili, errori, metriche di
business, e il cleanup heartbeat. Tutte le query PromQL che abbiamo mostrato
prima sono qui visualizzate in tempo reale.

---

## Slide 25 — Conclusioni

*(click)* Ricapitolando quello che abbiamo costruito: un servizio completo
orchestrato con Docker Compose, con metriche sia di infrastruttura che di
business, log strutturati aggregati e ricercabili, error tracking cloud, CI/CD
completamente automatizzato, e un deployment riproducibile su un server Arch
Linux reale.

*(click)* Alcune lezioni pratiche che abbiamo imparato durante il progetto. La
prima è la differenza tra porta host e porta container nella bridge network di
Docker — un errore che abbiamo effettivamente fatto e corretto. La seconda è che
i MySQL data volume devono essere named Docker volumes, non bind mount su path
relativi, altrimenti il CI/CD li sovrascrive ad ogni deploy. Sulla cardinalità
di Loki: promuovere troppi campi a label rompe le performance. Ansible non è
solo automazione — è documentazione eseguibile dell'infrastruttura. E infine, il
principio che ci sembra più importante: l'osservabilità non si aggiunge dopo, si
progetta insieme all'applicazione.

*(click)* Queste sono le tecnologie che abbiamo integrato nel progetto.

---

## Slide 26 — Q & A

Grazie per l'attenzione. Siamo disponibili per domande.

*(Possibili domande e risposte preparate:)*

**"Perché Loki invece di Elasticsearch?"**  Loki è pensato specificamente per i
log in ambiente Kubernetes/Docker, si integra nativamente con Grafana che già
usiamo, e ha un modello di indicizzazione più leggero — indicizza solo i label,
non il testo completo. Per il nostro use case è più che sufficiente ed evita di
aggiungere un componente pesante come Elasticsearch.

**"Come gestite i segreti in produzione?"**  Il file `vars.yml` di Ansible è
gitignored e contiene solo la chiave SSH pubblica e il PAT per il runner. Il
`.env` con tutte le credenziali vive sul server, non passa mai per il
repository. Il CI/CD lo copia da un percorso stabile sul filesystem del server
nella directory di lavoro del runner.

**"Perché un self-hosted runner invece di SSH dalla pipeline?"**  Con il runner
self-hosted non serve aprire SSH dall'esterno — il runner contatta GitHub
outbound, quindi funziona dietro NAT senza modifiche al firewall. È anche più
sicuro: non servono chiavi SSH da gestire come segreti su GitHub.

**"Cosa succede se il Background Scheduler si blocca?"**  Senza osservabilità
non lo sapremmo. Con `last_cleanup_success_timestamp` e la query `time() -
gauge`, possiamo creare un alert che scatta se il Gauge non si aggiorna per più
di trenta minuti. I link scaduti rimarrebbero nel database ma l'anomalia sarebbe
visibile immediatamente in Grafana.

**"Perché MySQL e non PostgreSQL?"**  Scelta pragmatica per un progetto
universitario — entrambi sarebbero adatti. MySQL 8 ha buon supporto Docker e
`mysql.connector` per Python è maturo. Non ci sono requisiti specifici che
richiedano PostgreSQL.

# Il motore come serie di patch

Questo repository (feder-cr/firefox_antidetect_patch, ramo `main`; in locale `C:/ff/repos/firefox_antidetect_patch`)
è il nostro Firefox scritto come **differenza da un tag di Mozilla**: una cartella
per funzione, applicate nell'ordine di `SERIES`. Il tag e il ramo sorgente sono in
`UPSTREAM.json`.

## Chi è la fonte

Su GitHub c'è solo questa serie: nessun ramo contiene l'albero di Firefox. Il codice si
modifica **nel sorgente locale**, `C:/ff/source`, sul ramo `source_branch` di
`UPSTREAM.json` (oggi `port/159-phase4`, che esiste solo in locale; serve un
clone che abbia il tag `mozilla_tag`). Se non c'è, o è vecchio, lo si ricrea dalla
serie: `python tools/engine.py apply --head port/159-phase4 --force`, che dà
sempre lo stesso commit, perché le date sono quelle del tag. La serie si
**genera** dal ramo con `export` e si **dimostra** identica con `verify`. La CI rifà
lo stesso percorso, `materialize`: tag di Mozilla, poi serie, poi l'albero dichiarato
in `UPSTREAM.json` (`exported_tree`). Si modificano a mano soltanto:

- `FEATURE.md` di ogni cartella (cosa fa, perché, test);
- `tools/layout.py` (in quale cartella va una funzione o un nostro file);
- `tools/inventory.json` (una voce per ogni file Mozilla che tocchiamo);
- `tools/hook-budget.json` e `tools/removed-budget.json` (solo verso il basso, vedi sotto);
- i campi a mano di `HOOKS.json` (`test`, `anchor`, `why`); `tools/hook-debt.json` solo con il comando `hook-debt`;
- `AGENTS.md`, `tools/`, `.github/`.

`hooks.patch`, `src/`, `MANIFEST.json`, `SERIES`, `exported_from`/`exported_tree` e i
workflow alla radice (`.github/workflows/`, copia di `platform/ci/src/.github/workflows/`
tranne `series.yml`) li scrive l'export: **non si modificano a mano**. Un workflow si
cambia nel sorgente, come ogni altro file.

## Comandi

```
python tools/engine.py status   # il sorgente si è spostato dall'ultimo export?
python tools/engine.py apply --head <ramo>   # nel sorgente: il tag + un commit per cartella (la pila a strati)
python tools/engine.py export   # riscrive la serie dal sorgente
python tools/engine.py verify   # la ricostruisce sul tag e la confronta: "identical" o rosso
python tools/engine.py check    # regole della serie, senza Firefox (gira anche in CI)
python tools/births.py --tree <albero>   # ogni punto in cui l'albero crea una richiesta di rete, contro tools/birth-ledger.json (CI: dopo materialize; `port` lo esegue alla fine)
python tools/engine.py shrink-budget   # abbassa i tetti dopo aver spostato logica
python tools/engine.py hook-debt   # toglie da tools/hook-debt.json le voci risolte (--summary: le conta)
python tools/engine.py hooks-list   # riscrive HOOKS.json di ogni cartella dalla serie (lo fa anche l'export)
python tools/engine.py drift --to <tag>  # quali nostri file Mozilla ha cambiato fino al tag nuovo
python tools/engine.py port --to <tag>   # tutte le cartelle a tre vie sul tag nuovo, tutti i conflitti in una corsa
python -m pytest -q tools/tests
```

## Il flusso di ogni modifica

1. In `C:/ff/source`, sul ramo sorgente: la modifica, con il suo test, e il commit.
2. Qui: `export` (scrive anche `HOOKS.json`), poi `verify` (deve dire *identical*).
3. `hook-debt` toglie le voci di debito risolte; nei `HOOKS.json` delle cartelle toccate
   si riempie a mano `test` (e `anchor`/`why` per un'àncora); poi `check`.
4. Se `export` si ferma su un file Mozilla nuovo: aggiungi la sua voce all'inventario
   e la funzione a `layout.FEATURES`; se si ferma su un nostro file nuovo, aggiungi il
   percorso a `layout.OWN_FILES`. Se `check` chiede un tetto per un file nuovo: un
   gancio nuovo è al massimo 5 righe.
5. Commit qui con lo stesso titolo del commit nel sorgente, poi push di entrambi.

## Le tre regole del prodotto (Federico, 31/10/2026)

1. **Niente dall'host.** Ogni valore che una pagina può leggere viene dall'identità
   dichiarata o dal codice di Firefox, mai dalla macchina o dal sistema su cui gira il
   browser. Un valore che nasce dall'host si toglie dove nasce (dichiarato, o calcolato
   con lo stesso codice su ogni sistema), non si corregge a valle.
2. **Stesso seed, stessi byte su ogni macchina.** La stessa identità su host diversi
   (Windows x86_64, Linux x86_64) dà lo stesso risultato: testo, canvas, WebGL,
   audio, media.
3. **Il riferimento è Windows retail, e si va solo verso di lui.** Il risultato è uguale,
   o coerente, con Firefox ufficiale su Windows. Linux si porta verso Windows, mai il
   contrario: uniformare gli host su qualcosa che nessun Windows vero produce (per
   esempio FreeType anche su Windows) è vietato.

Le misura il gate host del wrapper (`scripts/ci_host_gate.py`): ogni differenza fra host
è una fuga, ogni differenza dal retail lo è anche; le sole eccezioni sono rumore, ingressi
di rete e difetti noti con il lavoro che li chiude.

## Le regole del codice

### Il gancio: un punto fisso con un contratto

Il comportamento non cambia: nessun valore che una pagina legge, nessun byte di rete.

**Il principio**

- Un file di Mozilla porta solo **ganci**: righe di forma fissa che chiamano una funzione nostra.
- La **logica** sta nei nostri file (`Stealth*.cpp/.h/.mjs/.rs`), registrati in `layout.OWN_FILES`. I commenti lunghi stanno lì e in `FEATURE.md`: nel file di Mozilla la riga del gancio porta solo il marcatore.
- Le righe di Mozilla restano come le ha scritte Mozilla. Codice di Mozilla che non deve girare resta nell'albero, reso irraggiungibile da una guardia al suo unico ingresso e provato da un test: non si cancella e non si copia.
- Mai la logica di Mozilla copiata in un file nostro: dove un gancio avvolge o estende un'espressione di Mozilla, il conflitto al port è il segnale voluto (Mozilla ha cambiato proprio ciò che alteriamo), e va guardato.
- Ogni gancio è dichiarato in un elenco, ha un test con controllo negativo, e un gancio che sparisce fa fallire `check`.

**La scala: cosa provare prima di scrivere un gancio**

1. Nessun file di Mozilla: una pref che Firefox legge già, un dato dichiarato dal core, un'opzione di build.
2. Solo codice nostro, più una riga di registrazione.
3. Una guardia o un avviso in testa a una funzione.
4. Un avvolgimento (di un'espressione o di una funzione).
5. Un'àncora dentro una funzione, solo se serve un valore che Mozilla calcola a metà: ultima scelta, per i ganci nuovi e per quelli esistenti.

Per un gancio a metà funzione si prende la forma più portabile che dà lo stesso risultato, in questo ordine: guardia o avviso (bastano `this` e i parametri) → avvolgimento di funzione (il gancio tratta ciò che la funzione restituisce o scrive nei parametri d'uscita) → avvolgimento di espressione (altera un solo valore dove nasce) → àncora. La forma si sceglie leggendo la funzione.

**Le forme ammesse** (ogni gancio è una riga, con il marcatore sulla stessa riga; altre forme non esistono)

| Forma | Dove | Com'è |
|---|---|---|
| Guardia | prima istruzione di una funzione | `if (StealthX(this, aArg, &rv)) return rv;` |
| Avviso | prima istruzione di una funzione | `StealthX(this, aArg);` |
| Avvolgimento di espressione | la riga dove nasce il valore | l'espressione di Mozilla, identica, dentro la nostra chiamata: `return StealthX(<espressione>);` (1 riga riscritta) |
| Avvolgimento di funzione | la riga della firma | `Foo` di Mozilla diventa `Foo_Mozilla`; `Foo` è nostra, la chiama e ne tratta il risultato (1 riga riscritta, più 1 dichiarazione) |
| Valore dichiarato | la riga che dà il default | il valore sulla riga di Mozilla (pref dichiarate una volta sola; 1 riga riscritta) |
| Registrazione | include, build, file dichiarativi | `#include "StealthX.h"` in un blocco nostro dopo quelli di Mozilla, separato da una riga vuota; nei `moz.build` dopo la `]` di chiusura (`VAR += ["StealthX.cpp"]`); una riga in `.ipdl`, `.webidl`, `components.conf`, `jar.mn` |
| Membro | dichiarazione in una classe di Mozilla | una riga, subito dopo un membro esistente, mai l'ultima del blocco |
| Àncora | subito dopo un'istruzione di Mozilla nominata in `HOOKS.json` | `StealthX(this, &locale);` |

**Il contratto** (vale per ogni gancio fuori dalle cartelle `backport`; lo fa rispettare `tools/hook_contract.py`, regole C1-C11)

1. Una riga, senza logica: la chiamata e, nella guardia, il `return`. Niente `&&`, `||`, ternari, calcoli.
2. Il marcatore `// STEALTH-HOOK(<cartella della funzione>)` sulla stessa riga (o il commento del linguaggio del file).
3. Argomenti: solo `this`, i parametri della funzione o l'espressione avvolta; mai variabili locali (tranne l'àncora) né campi letti direttamente: la funzione nostra usa gli accessori pubblici.
4. Nessuna riga di Mozilla tolta o cambiata, tranne la riga unica delle tre forme che riscrivono.
5. Guardia e avviso sono la prima istruzione del corpo. Mai dentro un elenco di Mozilla né ultima riga di un blocco: fra noi e ciò che Mozilla aggiunge a ogni release deve restare una riga intatta.
6. Nessun commento nei file di Mozilla oltre il marcatore.
7. Nome `Stealth<Cosa>`, definita in un file nostro della stessa cartella.
8. Mai file interi di Mozilla cancellati o sostituiti. Mai valori nostri negli spazi numerati di Mozilla (bit di flag, enum, costanti IDL): Mozilla li assegna alla release dopo e la fusione non lo segnala (in 159 il bit 25 di `nsIWebBrowserChrome`, nostro flag, diventa `CHROME_MEDIA_PIP`). Le nostre costanti stanno nei nostri file, su valori che Mozilla lascia liberi, con un test che lo controlla (`juggler/tests/explicit_size_flag_is_free.test.mjs`).
9. Ogni gancio ha la sua riga in `HOOKS.json` della cartella.
10. Ogni gancio nomina un test con controllo negativo.

**`HOOKS.json`** (uno per cartella non backport, accanto a `hooks.patch`)

- Lo scrive l'export (o `python tools/engine.py hooks-list`): file, funzione ospite, `kind`, `form`, riga, riga tolta. `check` fallisce se non coincide con la serie: un gancio perso in una fusione non passa in silenzio.
- A mano solo `test` e, per l'àncora, `anchor` (l'istruzione di Mozilla che segue) e `why` (perché guardia e avvolgimenti non bastano). Un gancio il cui testo cambia perde i campi a mano e va riempito di nuovo.
- Grammatica di `test`: `gtest:Suite.Name`, `node:<percorso>#<titolo>`, `py:<percorso>::<nome>`, `wrapper:<percorso>::<test>`. `check` fallisce se il test nominato non esiste. Un gancio senza test è debito T1, un'àncora senza `anchor`/`why` è debito T2.

**Il test con controllo negativo**

- Gancio che dipende dal motore attivo: lo stesso test legge il valore a motore spento (quello di Firefox di serie) e a motore acceso (quello dichiarato) e i due devono differire; il valore dichiarato è uno che nessun runner ha. Il test fallisce se il gancio viene tolto o invertito.
- Gancio senza condizione (cosa tolta dalla build per tutti, come `glxtest`): il test prova l'effetto, `HOOKS.json` prova che il gancio c'è.
- Un gancio rifatto conserva i test che aveva, senza toccarli. Il nome del test va anche nella riga `Test:` di `FEATURE.md`.

**Tetti e debito**

- `tools/hook-budget.json` (righe nostre per file di Mozilla) e `tools/removed-budget.json` (righe di Mozilla tolte o riscritte, un file assente vale 0) scendono soltanto, **confrontati con `origin/main`**: un tetto sopra quello di `main` fallisce, e un file nuovo ha al massimo 5 righe di gancio e 5 tolte. Dopo aver spostato logica: `shrink-budget`. Un tetto non si alza: si sposta la logica. Una riga di Mozilla tolta va in conflitto al port come una aggiunta; se il blocco non deve girare o va esteso, resta intatto e il gancio gli sta accanto (esempio: il caricamento delle mappe dei caratteri in `InitializeFamily`).
- `tools/hook-debt.json` elenca ogni punto che oggi viola il contratto. `check` rifiuta una violazione che non è nell'elenco, una voce che non esiste più e una voce che l'elenco di `main` non ha: il debito scende soltanto. `python tools/engine.py hook-debt` toglie le voci risolte e non ne aggiunge mai; `--summary` le conta per regola e cartella. Ogni cartella rifatta toglie le sue voci.

### Le altre regole

- **Prima di ogni build di prova**, nel sorgente: `python build/stealth_check_sources.py`
  e `python build/stealth_check_build_files.py`. In circa mezzo minuto trovano ciò che
  la CI trova dopo un'ora:
  - un nome `mozilla::` che non sta in quel namespace;
  - una macro degli header di Windows;
  - un livello di log di nICEr fuori da `namespace mozilla`;
  - una lista di build non valida;
  - un nostro sorgente che nessuno compila.
- **Codice a monte portato in anticipo: categoria `backport`.** Quando ciò che manca è
  codice di un progetto che Mozilla vendorizza (es. wgpu in `third_party/rust/`), si porta
  il codice a monte com'è, non una nostra riscrittura. Non è logica nostra: niente tetti,
  ma la cartella ha `BACKPORT.json` (progetto, revisione vendorizzata, commit a monte,
  correzioni nostre, `drop_when`). `check` lo lega alla revisione: quando Mozilla ne
  vendorizza un'altra fallisce, e al port si prende il file di Mozilla tenendo solo ciò
  che a monte manca ancora. Solo dentro `third_party/rust/` e `Cargo.lock`; le
  `.cargo-checksum.json` delle crate toccate si aggiornano con i nuovi hash.
- **Backport di un commit di Mozilla** (un file fuori da `third_party/rust/`): solo come il diff di un commit del repo di Mozilla, in `platform/backports/<nome>/`, non dentro una nostra funzione.
  `BACKPORT.json` ha upstream `mozilla-firefox/firefox`, lo sha intero, il bug, la data, il sha256 del diff e `drop_when`; il diff sta nella cartella e `hooks.patch` lo porta byte per byte, e `check` rifiuta un diff ritoccato; `port` e `check --against <tag>` falliscono se il tag lo contiene già.
- **Ogni falsificazione passa da una pref** `zoom.stealth.*` / `stealthfox.*`; non si
  rinominano: sono il contratto con il core.
- **Mai i nomi dei sistemi studiati** (controlli dei siti, servizi di impronta, siti di
  test) né di browser concorrenti: né nel codice, né nei commenti, né nei commit. Si
  descrive il controllo.
- `stillborn/` è ciò che spegniamo alla nascita (aggiornamenti, telemetria, chiavi):
  le richieste che un Firefox vero fa restano, si spegne solo ciò che cambierebbe il
  browser installato.

## Commit e push

- Identità: `feder-cr <85809106+feder-cr@users.noreply.github.com>`, già impostata nel
  repo. Mai un'email personale nei commit.
- Prima di ogni push: `pytest`, `check`, `verify`; poi `git log -p origin/main..`
  cercando email e nomi dei sistemi studiati. Questi controlli sono locali e restano
  fuori da GitHub.
- Push: `git push origin main`. La CI (`.github/workflows/series.yml`) rifà
  le regole e la ricostruzione sul tag.
- Una build di prova: `gh workflow run release.yml --ref <ramo> -f kind=candidate`
  (compila le due gambe, Linux e Windows x86_64, LTO+PGO, con la cache; non pubblica nulla).
  Una candidata con i gtest parte anche da sola a ogni push su `main` e il lunedì alle 03:00 UTC.
  Le gambe compilano solo su un server Latitude.sh (`scripts/ci/latitude_node.py`): i suoi segreti stanno
  nell'environment `latitude-builder`, limitato a `main` e `latitude/*`, quindi il ramo di una
  build di prova deve essere uno di questi. Una release si lancia solo da `main`, mai da un
  tag: `release_plan.py` rifiuta il resto.
- **La cache di compilazione appartiene a un ramo.** GitHub dà a una build solo le
  cache del suo ramo e quelle di `main`. Un ramo nuovo legge la cache di `main`; un
  ramo che non parte da `main` compila a freddo (ore). Le build di prova si lanciano da
  `main` o da rami nati da `main`, mai da un ramo isolato.
- Release e push del motore solo dopo averne parlato con Federico.

## Lavori grandi: struttura a sub-agenti

Per spostare logica su molti file: Haiku 5.5 mappa un file o una funzione a testa,
in sola lettura, con riga e file per ogni affermazione. Sonnet 5.5 verifica ogni
mappa contro il sorgente. Chi integra scrive il codice. Un Sonnet separato rivede il
diff. Opus decide solo i casi contesi.

## Dove siamo

1. Fatto: la serie riproduce l'albero dichiarato in `UPSTREAM.json`, ricostruita e
   controllata in CI. Oggi è Firefox 159.0, la release firefox-54.
2. Fatto: la build della release parte dalla serie applicata al tag (`materialize`).
3. In corso: spostare la logica nei ganci, su un ramo sorgente dedicato, una funzione
   alla volta, dai file con più righe nostre (`hook-budget.json`).
4. Nuova versione di Firefox: solo dal tag della release stabile ufficiale, mai da
   una beta. In un clone che ha i due tag: `drift --to <nuovo>` dice quali nostri
   file Mozilla sono cambiati, `port --to <nuovo>` fa il ramo `port/<nuovo>` con una
   fusione a tre vie per cartella e l'elenco di tutti i conflitti. Si risolvono i
   marcatori su quel ramo, si cambia `mozilla_tag` e si esporta. Fatto così il
   passaggio 157 → 159 (firefox-54).

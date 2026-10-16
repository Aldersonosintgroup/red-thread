import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useCases } from '../context/CaseContext'

type Lang = 'en' | 'es'
type Action = 'sample' | 'settings' | 'new'

interface Step {
  title: string
  body: string[]
  action?: [Action, string]
}

const TEXT: Record<Lang, {
  heading: string; intro: string; quick: string; tabs: string; problems: string; manual: string; manualNote: string
  steps: Step[]; tabRows: [string, string][]; problemRows: [string, string][]
}> = {
  en: {
    heading: 'How to use The Red Thread',
    intro: 'Follow these steps in order the first time. Every step has a button that takes you to the right place.',
    quick: 'Quick start',
    tabs: 'What each tab in a case does',
    problems: 'If something goes wrong',
    manual: 'Full manual',
    manualNote: 'The complete user manual, with every screen explained.',
    steps: [
      { title: 'Try the practice case first',
        body: ['Load a made-up case that is already filled in. Nothing in it is real, so you can click anything without worry.',
          'Open its tabs (Timeline, Flags & Score, Network Map…) to see what the app produces.'],
        action: ['sample', 'Open the practice case'] },
      { title: 'Choose which AI reads your documents',
        body: ['Go to Settings and pick an AI provider. Claude gives the best results; Grok, ChatGPT, Gemini and others also work.',
          'Paste the API key from that company\'s website, click Save, then click Test connection. It should turn green.',
          'No key? Choose the built-in local engine: free and private (nothing leaves your computer), but slower and less accurate.'],
        action: ['settings', 'Open Settings'] },
      { title: 'Lock your case files with a password (recommended)',
        body: ['In Settings, under Security, turn on encryption and choose a passphrase.',
          'You will be shown a recovery key ONCE. Write it down or print it and keep it somewhere safe. Without the passphrase or the recovery key, nobody (including us) can open the files.'],
        action: ['settings', 'Open Settings'] },
      { title: 'Start a real case',
        body: ['Click "+ New Case" at the top left. Enter a title and a case number (any reference you like) and the person\'s details you already know.'],
        action: ['new', 'Start a new case'] },
      { title: 'Add the documents',
        body: ['In the Documents tab, click "Upload Documents" and select photos or PDFs of the records. You can select many at once.',
          'The AI reads each one. This takes a little while per page; you can keep working meanwhile.'] },
      { title: 'Check each document and click Commit',
        body: ['Click a document. The original is shown next to what the AI read. Fix anything it got wrong (names, dates, amounts).',
          'Then click "Commit & next". Only committed documents count toward the timeline, flags and analysis, so nothing unchecked ever reaches your results.'] },
      { title: 'Read the results',
        body: ['Timeline shows events in order. Flags & Score lists anything irregular. Financial lists every payment. Network Map shows who is connected to whom. Analysis writes possible explanations, each with its sources.',
          'Everything the AI suggests must be checked against the original documents.'] },
      { title: 'Save or share a report',
        body: ['In the Export tab, click "Download PDF Report" for a complete printable case file.',
          'Back up regularly: copy the whole RedThread folder (see the manual, "Backups").'] },
    ],
    tabRows: [
      ['Documents', 'Upload records, check what the AI read, fix it, and commit.'],
      ['Statements', 'Record testimony (what someone told you) and verified findings (what you proved, e.g. by DNA test). They count in the analysis and can raise flags.'],
      ['Network Map', 'People and organizations as bubbles. Click a bubble for details or to change its color.'],
      ['Analysis', 'AI-written summary and possible explanations, each with sources you can check.'],
      ['Financial', 'Every payment and fee found, with totals per currency.'],
      ['Timeline', 'All events in date order. Hide duplicates with the cleanup button.'],
      ['Actors', 'Everyone named in the documents. Merge two entries that are the same person. A red "+N other cases" tag means they are also named in other cases.'],
      ['Recurring Actors (sidebar)', 'People and organizations named in more than one case, most cases first. Confirm a match, or mark someone as a different person.'],
      ['Discrepancies', 'Places where documents disagree (e.g. two different birth dates).'],
      ['Flags & Score', 'Warning signs found, by severity, and an overall score.'],
      ['Notes', 'Your own notes about the case.'],
      ['Export', 'Download the case as a PDF report or a data file.'],
    ],
    problemRows: [
      ['A document says "failed" or reads nothing', 'Go to Settings and click Test connection. If it is red, re-enter the API key. Then open the document and click Re-read.'],
      ['The first document takes very long', 'Normal with the local engine: it loads the first time. The next ones are faster.'],
      ['A date or name is wrong', 'Open the document, correct the field, and commit again. Your correction replaces the AI\'s reading.'],
      ['Analysis button says it needs a cloud AI', 'The local engine is too small for analysis. Choose Claude, Grok, OpenAI, Gemini or another provider in Settings.'],
      ['I forgot my passphrase', 'Use the recovery key on the lock screen. Without either one, the files cannot be opened.'],
    ],
  },
  es: {
    heading: 'Cómo usar El Hilo Rojo',
    intro: 'La primera vez, siga estos pasos en orden. Cada paso tiene un botón que lo lleva al lugar correcto.',
    quick: 'Inicio rápido',
    tabs: 'Para qué sirve cada pestaña de un caso',
    problems: 'Si algo sale mal',
    manual: 'Manual completo',
    manualNote: 'El manual de usuario completo, con cada pantalla explicada.',
    steps: [
      { title: 'Pruebe primero el caso de práctica',
        body: ['Cargue un caso inventado que ya viene completo. Nada en él es real, así que puede hacer clic en todo sin preocuparse.',
          'Abra sus pestañas (Timeline, Flags & Score, Network Map…) para ver lo que produce la aplicación.'],
        action: ['sample', 'Abrir el caso de práctica'] },
      { title: 'Elija qué IA lee sus documentos',
        body: ['Vaya a Settings y elija un proveedor de IA. Claude da los mejores resultados; Grok, ChatGPT, Gemini y otros también funcionan.',
          'Pegue la clave de API del sitio web de esa empresa, haga clic en Save y luego en Test connection. Debe aparecer en verde.',
          '¿Sin clave? Elija el motor local incluido: gratuito y privado (nada sale de su computador), pero más lento y menos preciso.'],
        action: ['settings', 'Abrir Settings'] },
      { title: 'Proteja sus casos con contraseña (recomendado)',
        body: ['En Settings, en Security, active el cifrado y elija una frase de contraseña.',
          'Se le mostrará una clave de recuperación UNA sola vez. Anótela o imprímala y guárdela en un lugar seguro. Sin la contraseña ni la clave de recuperación, nadie (ni nosotros) puede abrir los archivos.'],
        action: ['settings', 'Abrir Settings'] },
      { title: 'Cree un caso real',
        body: ['Haga clic en "+ New Case" arriba a la izquierda. Ingrese un título, un número de caso (cualquier referencia) y los datos de la persona que ya conozca.'],
        action: ['new', 'Crear un caso nuevo'] },
      { title: 'Agregue los documentos',
        body: ['En la pestaña Documents, haga clic en "Upload Documents" y seleccione fotos o PDF de los registros. Puede seleccionar varios a la vez.',
          'La IA lee cada uno. Toma un momento por página; puede seguir trabajando mientras tanto.'] },
      { title: 'Revise cada documento y haga clic en Commit',
        body: ['Haga clic en un documento. Se muestra el original junto a lo que leyó la IA. Corrija lo que esté mal (nombres, fechas, montos).',
          'Luego haga clic en "Commit & next". Solo los documentos confirmados cuentan para la cronología, las alertas y el análisis, así que nada sin revisar llega a sus resultados.'] },
      { title: 'Lea los resultados',
        body: ['Timeline muestra los hechos en orden. Flags & Score lista lo irregular. Financial lista cada pago. Network Map muestra quién está conectado con quién. Analysis redacta posibles explicaciones, cada una con sus fuentes.',
          'Todo lo que sugiere la IA debe verificarse con los documentos originales.'] },
      { title: 'Guarde o comparta un informe',
        body: ['En la pestaña Export, haga clic en "Download PDF Report" para obtener el expediente completo listo para imprimir.',
          'Respalde con frecuencia: copie toda la carpeta RedThread (vea el manual, "Respaldos").'] },
    ],
    tabRows: [
      ['Documents', 'Subir registros, revisar lo que leyó la IA, corregirlo y confirmarlo.'],
      ['Statements', 'Registrar testimonios (lo que alguien le dijo) y hallazgos verificados (lo que usted comprobó, p. ej. con un examen de ADN). Cuentan en el análisis y pueden generar alertas.'],
      ['Network Map', 'Personas y organizaciones como burbujas. Haga clic en una para ver detalles o cambiar su color.'],
      ['Analysis', 'Resumen y posibles explicaciones redactados por IA, cada uno con fuentes verificables.'],
      ['Financial', 'Cada pago y arancel encontrado, con totales por moneda.'],
      ['Timeline', 'Todos los hechos por fecha. Oculte duplicados con el botón de limpieza.'],
      ['Actors', 'Todas las personas nombradas. Una dos entradas que sean la misma persona. Una etiqueta roja "+N other cases" indica que también aparecen en otros casos.'],
      ['Recurring Actors (barra lateral)', 'Personas y organizaciones nombradas en más de un caso, primero las que aparecen en más casos. Confirme una coincidencia o marque a alguien como otra persona.'],
      ['Discrepancies', 'Donde los documentos no coinciden (p. ej., dos fechas de nacimiento distintas).'],
      ['Flags & Score', 'Señales de alerta encontradas, por gravedad, y un puntaje general.'],
      ['Notes', 'Sus propias notas sobre el caso.'],
      ['Export', 'Descargar el caso como informe PDF o archivo de datos.'],
    ],
    problemRows: [
      ['Un documento dice "failed" o no lee nada', 'Vaya a Settings y haga clic en Test connection. Si sale en rojo, vuelva a ingresar la clave. Luego abra el documento y haga clic en Re-read.'],
      ['El primer documento tarda mucho', 'Es normal con el motor local: se carga la primera vez. Los siguientes son más rápidos.'],
      ['Una fecha o un nombre está mal', 'Abra el documento, corrija el campo y vuelva a confirmar. Su corrección reemplaza la lectura de la IA.'],
      ['El análisis dice que necesita una IA en la nube', 'El motor local es demasiado pequeño para el análisis. Elija Claude, Grok, OpenAI, Gemini u otro proveedor en Settings.'],
      ['Olvidé mi contraseña', 'Use la clave de recuperación en la pantalla de bloqueo. Sin ninguna de las dos, los archivos no se pueden abrir.'],
    ],
  },
}

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem('redthread-help-lang')
    if (saved === 'en' || saved === 'es') return saved
  } catch { /* storage unavailable */ }
  return navigator.language?.toLowerCase().startsWith('es') ? 'es' : 'en'
}

export function HelpPage() {
  const navigate = useNavigate()
  const { refreshCases, selectCase } = useCases()
  const [lang, setLang] = useState<Lang>(initialLang)
  const [busy, setBusy] = useState(false)
  const [showManual, setShowManual] = useState(false)
  const t = TEXT[lang]

  function chooseLang(next: Lang) {
    setLang(next)
    try { localStorage.setItem('redthread-help-lang', next) } catch { /* storage unavailable */ }
  }

  async function run(action: Action) {
    if (action === 'settings') navigate('/settings')
    if (action === 'new') { selectCase(null); navigate('/intake') }
    if (action === 'sample') {
      setBusy(true)
      try {
        const sample = await api.loadSampleCase()
        await refreshCases()
        selectCase(sample.id)
        navigate(`/cases/${sample.id}`)
      } finally {
        setBusy(false)
      }
    }
  }

  return (
    <div className="max-w-3xl mx-auto py-10 px-6 space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-white">{t.heading}</h2>
          <p className="text-sm text-neutral-400 mt-1">{t.intro}</p>
        </div>
        <div className="flex border border-neutral-700 rounded overflow-hidden shrink-0">
          {(['en', 'es'] as Lang[]).map((l) => (
            <button key={l} onClick={() => chooseLang(l)}
              className={`px-3 py-1.5 text-xs font-semibold ${lang === l ? 'bg-red-700 text-white' : 'text-neutral-400 hover:text-white'}`}>
              {l === 'en' ? 'English' : 'Español'}
            </button>
          ))}
        </div>
      </div>

      <section>
        <h3 className="text-sm uppercase tracking-wide text-neutral-500 mb-3">{t.quick}</h3>
        <ol className="space-y-3">
          {t.steps.map((step, i) => (
            <li key={i} className="flex gap-4 border border-neutral-800 rounded p-4">
              <div className="w-8 h-8 shrink-0 rounded-full bg-red-700 text-white font-semibold flex items-center justify-center">{i + 1}</div>
              <div className="flex-1 min-w-0 space-y-1.5">
                <h4 className="text-white font-medium">{step.title}</h4>
                {step.body.map((p, j) => <p key={j} className="text-sm text-neutral-400 leading-relaxed">{p}</p>)}
                {step.action && (
                  <button onClick={() => run(step.action![0])} disabled={busy}
                    className="mt-1 bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 text-white text-sm px-3 py-1.5 rounded">
                    {step.action[1]} →
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wide text-neutral-500 mb-3">{t.tabs}</h3>
        <table className="w-full text-sm border border-neutral-800 rounded">
          <tbody className="divide-y divide-neutral-800">
            {t.tabRows.map(([tab, what]) => (
              <tr key={tab}><td className="px-3 py-2 text-white font-medium whitespace-nowrap align-top">{tab}</td><td className="px-3 py-2 text-neutral-400">{what}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wide text-neutral-500 mb-3">{t.problems}</h3>
        <div className="space-y-2">
          {t.problemRows.map(([problem, fix]) => (
            <div key={problem} className="border border-neutral-800 rounded px-4 py-3">
              <div className="text-sm text-white">{problem}</div>
              <div className="text-sm text-neutral-400 mt-0.5">{fix}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between gap-4 mb-3">
          <div>
            <h3 className="text-sm uppercase tracking-wide text-neutral-500">{t.manual}</h3>
            <p className="text-xs text-neutral-600">{t.manualNote}</p>
          </div>
          <button onClick={() => setShowManual((v) => !v)} className="bg-neutral-800 hover:bg-neutral-700 text-white text-sm px-3 py-1.5 rounded">
            {showManual ? '▲' : '▼'} {t.manual}
          </button>
        </div>
        {showManual && (
          <iframe key={lang} src={`/manual.html?lang=${lang}`} title={t.manual}
            className="w-full h-[80vh] rounded border border-neutral-800 bg-white" />
        )}
      </section>
    </div>
  )
}

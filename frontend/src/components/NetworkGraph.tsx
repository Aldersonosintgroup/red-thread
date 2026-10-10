import cytoscape, { type Core } from 'cytoscape'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { ActorDetailsPanel } from './ActorDetailsPanel'
import type { Actor, Edge, WatchlistEntityOut } from '../types'

const CATEGORY_COLOR: Record<string, string> = {
  RED: '#dc2626',
  ORANGE: '#ea580c',
  YELLOW: '#ca8a04',
}
const SUBJECT_COLOR = '#7c3aed'
const DEFAULT_COLOR = '#475569'
const ROLE_PALETTE = ['#06b6d4', '#f97316', '#22c55e', '#eab308', '#ec4899', '#3b82f6', '#a855f7', '#14b8a6', '#f43f5e']

type ColorMode = 'watchlist' | 'role' | 'custom'

export function NetworkGraph({ caseId }: { caseId: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actors, setActors] = useState<Actor[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [watchlist, setWatchlist] = useState<WatchlistEntityOut[]>([])
  const [colorMode, setColorMode] = useState<ColorMode>('watchlist')
  const [selectedActorId, setSelectedActorId] = useState<string | null>(null)
  // A color picked in the details panel is painted straight onto its node;
  // this skips the full re-render (and re-layout) the state update would cause.
  const skipRenderRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [actorList, edgeList, watchlistEntities] = await Promise.all([
          api.listActors(caseId),
          api.listEdges(caseId),
          api.listWatchlist(),
        ])
        if (cancelled) return
        setActors(actorList)
        setEdges(edgeList)
        setWatchlist(watchlistEntities)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load network map.')
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [caseId])

  useEffect(() => {
    if (skipRenderRef.current) {
      skipRenderRef.current = false
      return
    }
    if (actors.length > 0) renderGraph(actors, edges, watchlist, colorMode)
    return () => {
      cyRef.current?.destroy()
      cyRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actors, edges, watchlist, colorMode])

  // Opening or closing the details panel changes the map's width: refit so
  // no bubble is hidden behind the panel.
  const panelOpen = selectedActorId !== null
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const id = requestAnimationFrame(() => { cy.resize(); cy.fit(undefined, 60); cy.center() })
    return () => cancelAnimationFrame(id)
  }, [panelOpen])

  function colorFor(actor: Actor, mode: ColorMode, actorList: Actor[], watchlistEntities: WatchlistEntityOut[]): string {
    if (actor.is_subject) return SUBJECT_COLOR
    const watchlistEntity = actor.watchlist_match_id ? watchlistEntities.find((w) => w.id === actor.watchlist_match_id) : undefined
    const watchlistColor = watchlistEntity ? CATEGORY_COLOR[watchlistEntity.category] ?? DEFAULT_COLOR : DEFAULT_COLOR
    // Custom mode: an actor without a custom color keeps its watchlist color.
    if (mode === 'custom') return actor.custom_color ?? watchlistColor
    if (mode === 'role') return actor.role ? buildRoleColorMap(actorList).get(actor.role) ?? DEFAULT_COLOR : DEFAULT_COLOR
    return watchlistColor
  }

  function handleColorChange(updated: Actor) {
    const next = actors.map((a) => (a.id === updated.id ? updated : a))
    if (colorMode === 'custom' && cyRef.current) {
      cyRef.current.$id(updated.id).style('background-color', colorFor(updated, 'custom', next, watchlist))
      skipRenderRef.current = true
      setActors(next)
    } else {
      setActors(next)
      setColorMode('custom') // show the color that was just picked
    }
  }

  function renderGraph(actorList: Actor[], edgeList: Edge[], watchlistEntities: WatchlistEntityOut[], mode: ColorMode) {
    if (!containerRef.current) return

    const nodes = actorList.map((actor) => ({
      data: { id: actor.id, label: actor.canonical_name },
      style: { 'background-color': colorFor(actor, mode, actorList, watchlistEntities) },
      classes: actor.is_subject ? 'subject' : '',
    }))

    const edges = edgeList.map((edge) => ({
      data: { id: edge.id, source: edge.source_actor_id, target: edge.target_actor_id },
    }))

    cyRef.current?.destroy()
    const cy = cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            color: '#ffffff',
            'font-size': 11,
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'text-wrap': 'wrap',
            'text-max-width': '100px',
            width: 36,
            height: 36,
            'border-width': 2,
            'border-color': '#0b0e14',
          },
        },
        {
          selector: 'node.subject',
          style: {
            width: 56,
            height: 56,
            'font-size': 13,
            'font-weight': 'bold',
            'border-width': 3,
            'border-color': '#ffffff',
          },
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 4, 'border-color': '#ffffff' },
        },
        {
          selector: 'edge',
          style: {
            width: 1.5,
            'line-color': '#4b5563',
            'curve-style': 'bezier',
            'target-arrow-shape': 'none',
          },
        },
      ],
      // A small case would otherwise zoom in until labels overflow the frame.
      maxZoom: 1.4,
      layout: { name: 'concentric', concentric: (n: cytoscape.NodeSingular) => (n.hasClass('subject') ? 2 : 1), levelWidth: () => 1, minNodeSpacing: 60, padding: 60 },
    })
    cy.on('tap', 'node', (event) => setSelectedActorId(event.target.id()))
    cy.on('tap', (event) => { if (event.target === cy) setSelectedActorId(null) })
    cy.on('mouseover', 'node', () => { if (containerRef.current) containerRef.current.style.cursor = 'pointer' })
    cy.on('mouseout', 'node', () => { if (containerRef.current) containerRef.current.style.cursor = 'default' })
    cy.autounselectify(false)
    if (selectedActorId) cy.$id(selectedActorId).select()
    // Re-measure once the browser has laid out the (possibly narrowed) frame.
    requestAnimationFrame(() => { if (cyRef.current === cy) { cy.resize(); cy.fit(undefined, 60); cy.center() } })
    cyRef.current = cy
  }

  const roleColorOf = buildRoleColorMap(actors)
  const rolesPresent = [...roleColorOf.keys()]

  return (
    <div className="h-full flex flex-col">
      {error && <p className="text-red-400 text-sm mb-2">{error}</p>}

      <div className="flex items-center justify-between mb-3">
        <div className="flex gap-4 text-xs text-neutral-400 flex-wrap">
          {colorMode === 'watchlist' && (
            <>
              <LegendDot color={SUBJECT_COLOR} label="Subject" />
              <LegendDot color={CATEGORY_COLOR.RED} label="RED watchlist" />
              <LegendDot color={CATEGORY_COLOR.ORANGE} label="ORANGE watchlist" />
              <LegendDot color={CATEGORY_COLOR.YELLOW} label="YELLOW watchlist" />
              <LegendDot color={DEFAULT_COLOR} label="Unmatched" />
            </>
          )}
          {colorMode === 'role' && (
            <>
              <LegendDot color={SUBJECT_COLOR} label="Subject" />
              {rolesPresent.map((role) => (
                <LegendDot key={role} color={roleColorOf.get(role)!} label={role} />
              ))}
              <LegendDot color={DEFAULT_COLOR} label="No role recorded" />
            </>
          )}
          {colorMode === 'custom' && (
            <>
              <LegendDot color={SUBJECT_COLOR} label="Subject" />
              <LegendDot color={DEFAULT_COLOR} label="Click a bubble to set its color; others keep their watchlist color" />
            </>
          )}
        </div>

        <div className="flex gap-1 bg-neutral-900 border border-neutral-800 rounded p-0.5 shrink-0">
          {(['watchlist', 'role', 'custom'] as ColorMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setColorMode(mode)}
              className={`text-xs px-2.5 py-1 rounded capitalize ${
                colorMode === mode ? 'bg-neutral-700 text-white' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      <div className="relative flex-1 min-h-0">
        <div ref={containerRef} style={{ width: selectedActorId ? 'calc(100% - 20rem)' : '100%' }}
          className="absolute inset-y-0 left-0 bg-neutral-950 border border-neutral-800 rounded cytoscape-container" />
        {selectedActorId && (
          <ActorDetailsPanel
            key={selectedActorId}
            caseId={caseId}
            actorId={selectedActorId}
            onColorChange={handleColorChange}
            onClose={() => { setSelectedActorId(null); cyRef.current?.elements().unselect() }}
          />
        )}
      </div>
      {actors.length > 0 && !selectedActorId && (
        <p className="text-neutral-600 text-xs mt-1.5">Click a bubble for details and to change its color. Drag to rearrange.</p>
      )}
      {actors.length === 0 && (
        <p className="text-neutral-600 text-sm mt-2">
          No actors yet — commit a document in the Documents tab to populate the map.
        </p>
      )}
    </div>
  )
}

function buildRoleColorMap(actors: Actor[]): Map<string, string> {
  const roles = [...new Set(actors.filter((a) => !a.is_subject && a.role).map((a) => a.role as string))].sort()
  return new Map(roles.map((role, i) => [role, ROLE_PALETTE[i % ROLE_PALETTE.length]]))
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
      {label}
    </span>
  )
}

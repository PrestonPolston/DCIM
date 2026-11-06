import type { ComponentType } from 'react'
import Basics from './Basics'
import Location from './Location'
import type { SectionProps } from './model'

// Device form sections, in display order. To add fields to Power/Physical/Project,
// give the section a `Fields` component (and extend FormValues/toBody in model.ts).
// Sections without `Fields` render nothing.
export interface SectionDef {
  id: 'basics' | 'location' | 'power' | 'physical' | 'project'
  title: string
  Fields?: ComponentType<SectionProps>
}

export const SECTIONS: SectionDef[] = [
  { id: 'basics', title: 'Basics', Fields: Basics },
  { id: 'location', title: 'Location', Fields: Location },
  { id: 'power', title: 'Power' }, // fields pending DB Architect model
  { id: 'physical', title: 'Physical' }, // fields pending DB Architect model
  { id: 'project', title: 'Project' }, // fields pending DB Architect model
]

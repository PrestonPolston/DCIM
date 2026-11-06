// Row route: the 3D row is the DEFAULT view (Preston D1). ?view=2d, no WebGL or a
// 3D crash show the existing 2D row front (row-front.md), which stays the fallback.
import { useSearchParams } from 'react-router'
import { hasWebGL, NO_3D_TEXT } from '../lib/webgl'
import Row3DPage from './Row3DPage'
import RowFrontPage from './RowFrontPage'

export default function RowPage() {
  const [params] = useSearchParams()
  if (params.get('view') === '2d') return <RowFrontPage />
  if (!hasWebGL()) return <RowFrontPage notice={NO_3D_TEXT} noticeDetail="WebGL is unavailable or blocked in this browser." />
  return <Row3DPage />
}

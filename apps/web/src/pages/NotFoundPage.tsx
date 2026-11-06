import { Link } from 'react-router'

export default function NotFoundPage() {
  return (
    <section>
      <h1>Page not found</h1>
      <p>
        <Link to="/devices">Go to Devices</Link>
      </p>
    </section>
  )
}

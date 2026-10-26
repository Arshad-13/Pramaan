import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" description="That address does not lead anywhere in Pramaan." />
      <Button asChild>
        <Link to="/">Back to overview</Link>
      </Button>
    </>
  )
}

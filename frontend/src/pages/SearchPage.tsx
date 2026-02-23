import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { searchHats } from '../api/search';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', searchTerm],
    queryFn: () => searchHats(searchTerm),
    enabled: searchTerm.length > 0,
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSearchTerm(query.trim());
  }

  return (
    <>
      <h1 className="mb-3">Search</h1>

      <form onSubmit={handleSubmit} className="mb-3">
        <div className="input-group">
          <input
            type="search"
            className="form-control"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by color, style, size..."
          />
          <button type="submit" className="btn btn-primary">Go</button>
        </div>
      </form>

      {!searchTerm && (
        <div className="text-center py-5 text-secondary">
          <p>Search across all hats by color, style, condition, or size</p>
          <p className="small">Use multiple terms for AND search: "blue a-game"</p>
        </div>
      )}

      {isLoading && <LoadingSpinner />}
      {error && <div className="alert alert-danger">{String(error)}</div>}

      {data && searchTerm && (
        <>
          <div className="text-secondary small mb-3">
            {data.length} result{data.length !== 1 ? 's' : ''} for "{searchTerm}"
          </div>
          {data.length === 0 ? (
            <div className="text-center py-5 text-secondary">
              <p>No hats found</p>
            </div>
          ) : (
            data.map(hat => (
              <Link key={hat.id} to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none text-body">
                <div className="card-body d-flex gap-3">
                  {hat.photo_path ? (
                    <img src={`/uploads/${hat.photo_path}`} alt="" className="rounded flex-shrink-0" style={{ width: 72, height: 72, objectFit: 'cover' }} />
                  ) : (
                    <div className="rounded flex-shrink-0" style={{ width: 72, height: 72, background: 'var(--color-border)' }} />
                  )}
                  <div className="flex-grow-1" style={{ minWidth: 0 }}>
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="fw-semibold">{hat.display_id || `#${hat.id}`}</div>
                      <ConditionBadge condition={hat.condition} />
                    </div>
                    <div className="text-secondary small mb-1">
                      {hat.style.replace(/_/g, ' ')} &middot; {hat.size.replace(/_/g, ' ')}
                    </div>
                    <ColorSwatches colors={hat.colors} />
                  </div>
                </div>
              </Link>
            ))
          )}
        </>
      )}
    </>
  );
}

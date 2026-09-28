import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { ConditionBadge } from './ConditionBadge';

vi.mock('../../api/hats', () => ({
  getStyles: vi.fn(async () => []),
  getSizes: vi.fn(async () => []),
  getConditions: vi.fn(async () => [
    { value: 'new_with_tags', label: 'New With Tags' },
    { value: 'worn', label: 'Worn' },
  ]),
}));

describe('ConditionBadge', () => {
  it("prints the server's label, not the stored value with its underscores swapped out", async () => {
    renderWithProviders(<ConditionBadge condition="new_with_tags" />);
    expect(await screen.findByText('New With Tags')).toHaveClass('hr-badge-new_with_tags');
    expect(screen.queryByText('new with tags')).not.toBeInTheDocument();
  });
});

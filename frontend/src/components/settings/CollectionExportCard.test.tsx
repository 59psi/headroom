import { describe, it, expect, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { CollectionExportCard } from './CollectionExportCard';
import { InventoryReportCard } from './InventoryReportCard';

// jsdom cannot navigate; cancel the anchor's default action so a click runs
// the card's handler without jsdom logging "Not implemented: navigation".
function blockNavigation() {
  const stop = (e: Event) => e.preventDefault();
  document.addEventListener('click', stop);
  return () => document.removeEventListener('click', stop);
}

let unblock: (() => void) | null = null;
afterEach(() => { unblock?.(); unblock = null; });

describe('CollectionExportCard', () => {
  it('builds the download link from the options, values and disposed hats off by default', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CollectionExportCard />);
    const link = screen.getByRole('link', { name: 'Download .zip' });

    expect(link).toHaveAttribute('href', '/api/admin/collection-export?title=The+Collection');

    const title = screen.getByLabelText('Export title');
    await user.clear(title);
    await user.type(title, '  Hats  ');
    await user.click(screen.getByLabelText(/Include estimated values/));
    await user.click(screen.getByLabelText('Include hats you no longer own'));

    expect(link).toHaveAttribute(
      'href',
      '/api/admin/collection-export?title=Hats&include_values=true&include_disposed=true',
    );
  });

  it('leads with whether the money goes in, and follows the checkbox', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CollectionExportCard />);
    expect(screen.getByText('No prices', { selector: '.hr-pill' })).toBeInTheDocument();

    await user.click(screen.getByLabelText(/Include estimated values/));
    expect(screen.getByText('With values', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('says the zip is being built, since the browser shows nothing until it is', async () => {
    const user = userEvent.setup();
    unblock = blockNavigation();
    renderWithProviders(<CollectionExportCard />);

    await user.click(screen.getByRole('link', { name: 'Download .zip' }));
    expect(await screen.findByText(/Building the \.zip/)).toBeInTheDocument();
  });
});

describe('InventoryReportCard', () => {
  it('opens either report in a new tab, one tap each', () => {
    renderWithProviders(<InventoryReportCard />);

    const active = screen.getByRole('link', { name: 'Open report' });
    const all = screen.getByRole('link', { name: 'Open with disposed hats' });
    expect(active).toHaveAttribute('href', '/api/admin/inventory-report');
    expect(all).toHaveAttribute('href', '/api/admin/inventory-report?include_disposed=true');
    for (const a of [active, all]) {
      expect(a).toHaveAttribute('target', '_blank');
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  it('leads with a status like every other card — this one carries the values', () => {
    renderWithProviders(<InventoryReportCard />);
    expect(screen.getByText('With values', { selector: '.hr-pill' })).toBeInTheDocument();
  });
});

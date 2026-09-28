import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Panel } from './Panel';
import { StatusPill } from './StatusPill';

/**
 * The card shell every settings card is built on. Its contract is structural:
 * a landmark named by its title at the right heading level (Settings has an
 * h1, so cards are h2; a detail page's sections under an h2 are h3), the long
 * explanation folded but still present, and the parts in a fixed order.
 */
describe('Panel', () => {
  it('is a region named by its title, with an h2 by default', () => {
    render(<Panel title="API key">body</Panel>);
    const region = screen.getByRole('region', { name: 'API key' });
    expect(within(region).getByRole('heading', { level: 2, name: 'API key' })).toHaveClass('card-title');
    expect(region.tagName).toBe('SECTION');
    expect(region).toHaveClass('card', 'hr-panel');
  });

  it('as="h3" drops a level for cards nested under a page section', () => {
    render(<Panel title="Colors" as="h3">body</Panel>);
    expect(screen.getByRole('heading', { level: 3, name: 'Colors' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Colors' })).toBeInTheDocument();
  });

  it('two panels on one page each name their own region', () => {
    render(
      <>
        <Panel title="API key">a</Panel>
        <Panel title="Backups">b</Panel>
      </>,
    );
    expect(within(screen.getByRole('region', { name: 'API key' })).getByText('a')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Backups' })).getByText('b')).toBeInTheDocument();
  });

  it('puts status and actions in the header beside the title', () => {
    render(
      <Panel
        title="API key"
        status={<StatusPill tone="ok">Configured</StatusPill>}
        actions={<button type="button">Refresh</button>}
        description="Used for hat analysis."
      >
        body
      </Panel>,
    );
    const header = screen.getByRole('heading', { name: 'API key' }).closest('header')!;
    expect(within(header).getByText('Configured')).toBeInTheDocument();
    expect(within(header).getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
    expect(within(header).getByText('Used for hat analysis.')).toHaveClass('hr-panel-desc');
  });

  it('no status and no actions: no empty aside', () => {
    const { container } = render(<Panel title="API key">body</Panel>);
    expect(container.querySelector('.hr-panel-aside')).toBeNull();
    expect(container.querySelector('.hr-panel-desc')).toBeNull();
  });

  it('folds the long explanation behind "How this works", closed, but still in the page', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Panel title="Backups" help={<p>Nightly at 03:00; the last seven are kept.</p>}>body</Panel>,
    );
    const details = container.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    // Present in the DOM (find-in-page, and the settings search, can reach it).
    expect(within(details).getByText('Nightly at 03:00; the last seven are kept.')).toBeInTheDocument();

    await user.click(screen.getByText('How this works'));
    expect(details).toHaveAttribute('open');
  });

  it('takes a custom disclosure label', () => {
    render(<Panel title="Backups" help="Details." helpLabel="What gets backed up">body</Panel>);
    expect(screen.getByText('What gets backed up').tagName).toBe('SUMMARY');
    expect(screen.queryByText('How this works')).not.toBeInTheDocument();
  });

  it('no help: no disclosure', () => {
    const { container } = render(<Panel title="Backups">body</Panel>);
    expect(container.querySelector('details')).toBeNull();
  });

  it('renders the footer after the body', () => {
    const { container } = render(
      <Panel title="API key" footer={<button type="button" className="btn btn-primary">Save key</button>}>
        <input aria-label="Key" />
      </Panel>,
    );
    const body = container.querySelector('.hr-panel-body')!;
    const foot = container.querySelector('.hr-panel-foot')!;
    expect(within(foot as HTMLElement).getByRole('button', { name: 'Save key' })).toBeInTheDocument();
    expect(body.compareDocumentPosition(foot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('keeps the fixed order: header, help, body, footer', () => {
    const { container } = render(
      <Panel title="T" help="H" footer={<span>F</span>}>B</Panel>,
    );
    const order = Array.from(container.querySelector('.card-body')!.children).map(el => el.className);
    expect(order).toEqual(['hr-panel-head', 'hr-panel-help', 'hr-panel-body', 'hr-panel-foot']);
  });

  it.each([
    ['nothing', undefined],
    ['null', null],
    ['false (a `cond && …` that did not match)', false],
  ])('no body wrapper for %s', (_label, children) => {
    const { container } = render(<Panel title="T">{children}</Panel>);
    expect(container.querySelector('.hr-panel-body')).toBeNull();
  });

  it('featured, className and id land on the section', () => {
    render(<Panel title="API key" featured className="extra" id="api-key">body</Panel>);
    const region = screen.getByRole('region', { name: 'API key' });
    expect(region).toHaveClass('hr-feature', 'extra');
    expect(region).toHaveAttribute('id', 'api-key');
  });

  it('not featured: no sunset stripe', () => {
    render(<Panel title="API key">body</Panel>);
    expect(screen.getByRole('region', { name: 'API key' })).not.toHaveClass('hr-feature');
  });
});

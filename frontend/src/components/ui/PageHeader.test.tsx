import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import type { ReactElement } from 'react';
import { PageHeader } from './PageHeader';
import { StatusPill } from './StatusPill';

/**
 * The top of the case, room, collection and hat pages and Settings (Home has
 * its hero; login, the tag landing and the guest pages their own shells).
 * Its contract is structural: exactly one h1
 * (the page's name — nothing else in the head may be a heading), the "up"
 * link before it, a count a screen reader hears change, and the parts in a
 * fixed place so a page cannot put its actions somewhere of its own again.
 */
function renderHead(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function head(container: HTMLElement): HTMLElement {
  return container.querySelector('header.hr-page-head')!;
}

describe('PageHeader', () => {
  it('is a header with the title as the one h1, in the display face', () => {
    const { container } = renderHead(<PageHeader title="Cases" />);
    const h1 = screen.getByRole('heading', { level: 1, name: 'Cases' });
    expect(head(container)).toContainElement(h1);
    expect(screen.getAllByRole('heading')).toHaveLength(1);
    // No class of its own: the global `h1` rule's face and size apply.
    expect(h1).not.toHaveAttribute('class');
  });

  it('code sets an identifier title in mono', () => {
    renderHead(<PageHeader code title="A-001" />);
    expect(screen.getByRole('heading', { level: 1, name: 'A-001' })).toHaveClass('hr-page-head-code');
  });

  it('takes a title with a link inside it (the hat id whose case half is a breadcrumb)', () => {
    renderHead(<PageHeader code title={<><a href="/cases/A-029">A-029</a>-01</>} />);
    const h1 = screen.getByRole('heading', { level: 1, name: 'A-029-01' });
    expect(within(h1).getByRole('link', { name: 'A-029' })).toHaveAttribute('href', '/cases/A-029');
  });

  describe('back link', () => {
    it('goes where it says, named by its destination, before the title', () => {
      renderHead(<PageHeader back={{ to: '/cases', label: 'Cases' }} title="New case" />);
      const back = screen.getByRole('link', { name: 'Cases' });
      expect(back).toHaveAttribute('href', '/cases');
      expect(back).toHaveClass('hr-page-head-back');
      const h1 = screen.getByRole('heading', { level: 1 });
      expect(back.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('carries a tooltip when given one, without it replacing the name', () => {
      renderHead(
        <PageHeader
          back={{ to: '/hats/7', label: 'A-001-01', title: 'Back to this hat without saving' }}
          title="Edit hat"
        />,
      );
      const back = screen.getByRole('link', { name: 'A-001-01' });
      expect(back).toHaveAttribute('title', 'Back to this hat without saving');
    });

    it('none given: no link at all', () => {
      renderHead(<PageHeader title="Cases" />);
      expect(screen.queryByRole('link')).toBeNull();
    });
  });

  describe('count', () => {
    it('sits beside the title in a polite live region, noun heard but not shown', () => {
      renderHead(
        <PageHeader title="Hats" count={<>12 of 128<span className="visually-hidden"> hats</span></>} />,
      );
      const count = screen.getByText('12 of 128');
      expect(count).toHaveClass('hr-page-head-count');
      expect(count).toHaveAttribute('aria-live', 'polite');
      expect(count).toHaveTextContent('12 of 128 hats');
      // Beside the h1, in the title row — not in the actions at the right.
      expect(count.parentElement).toBe(screen.getByRole('heading', { level: 1 }).parentElement);
    });

    it('a count of 0 is still a count', () => {
      const { container } = renderHead(<PageHeader title="Hats" count={0} />);
      expect(container.querySelector('.hr-page-head-count')).toHaveTextContent('0');
    });

    it.each([
      ['nothing', undefined],
      ['an empty string (no data yet)', ''],
      ['false (a `cond && …` that did not match)', false],
    ])('no count element for %s', (_label, count) => {
      const { container } = renderHead(<PageHeader title="Hats" count={count} />);
      expect(container.querySelector('.hr-page-head-count')).toBeNull();
      expect(container.querySelector('[aria-live]')).toBeNull();
    });
  });

  describe('summary', () => {
    it('is one line under the title, and can carry links and pills', () => {
      const { container } = renderHead(
        <PageHeader
          title="A-001"
          summary={<><span>Archive · <a href="/rooms/2">Den</a></span><StatusPill tone="info">Full</StatusPill></>}
        />,
      );
      const summary = container.querySelector('.hr-page-head-summary')!;
      expect(summary.tagName).toBe('P');
      expect(within(summary as HTMLElement).getByRole('link', { name: 'Den' })).toHaveAttribute('href', '/rooms/2');
      expect(within(summary as HTMLElement).getByText('Full')).toBeInTheDocument();
      const h1 = screen.getByRole('heading', { level: 1 });
      expect(h1.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it.each([
      ['nothing', undefined],
      ['false (no data yet)', false],
    ])('no summary element for %s', (_label, summary) => {
      const { container } = renderHead(<PageHeader title="Cases" summary={summary} />);
      expect(container.querySelector('.hr-page-head-summary')).toBeNull();
    });
  });

  describe('status and actions', () => {
    it('share the aside, status first — where Panel puts them', () => {
      const { container } = renderHead(
        <PageHeader
          title="A-001-01"
          status={<span className="badge">HYDRO</span>}
          actions={<button type="button">Edit</button>}
        />,
      );
      const aside = container.querySelector('.hr-page-head-aside') as HTMLElement;
      expect(within(aside).getByText('HYDRO')).toBeInTheDocument();
      expect(within(aside).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
      expect(Array.from(aside.children).map(el => el.textContent)).toEqual(['HYDRO', 'Edit']);
    });

    it('the aside comes after the title block, so a phone wraps it underneath', () => {
      const { container } = renderHead(
        <PageHeader title="Hats" actions={<a href="/hats/new">Add hat</a>} />,
      );
      expect(Array.from(head(container).children).map(el => el.className))
        .toEqual(['hr-page-head-main', 'hr-page-head-aside']);
    });

    it('neither: no empty aside', () => {
      const { container } = renderHead(<PageHeader title="Rooms" summary="2 rooms" />);
      expect(container.querySelector('.hr-page-head-aside')).toBeNull();
    });
  });

  describe('layout flags', () => {
    it('a bare title is not stacked: the aside centers on it', () => {
      const { container } = renderHead(<PageHeader title="Hats" actions={<a href="/x">X</a>} />);
      expect(head(container)).not.toHaveClass('is-stacked');
      expect(head(container)).not.toHaveClass('has-summary');
    });

    it('a back link stacks the title block', () => {
      const { container } = renderHead(<PageHeader back={{ to: '/cases', label: 'Cases' }} title="New case" />);
      expect(head(container)).toHaveClass('is-stacked');
      expect(head(container)).not.toHaveClass('has-summary');
    });

    it('a summary stacks it too, and claims its minimum width', () => {
      const { container } = renderHead(<PageHeader title="Cases" summary="3 cases" />);
      expect(head(container)).toHaveClass('is-stacked', 'has-summary');
    });

    it('a summary that did not render does not stack it', () => {
      const { container } = renderHead(<PageHeader title="Cases" summary={false} />);
      expect(head(container)).not.toHaveClass('is-stacked');
      expect(head(container)).not.toHaveClass('has-summary');
    });
  });

  describe('loading', () => {
    it('holds the title place with a bar, not an empty heading', () => {
      const { container } = renderHead(<PageHeader loading />);
      expect(screen.queryByRole('heading')).toBeNull();
      const bar = container.querySelector('.hr-page-head-skel')!;
      // `.h1` for the title's exact line height; decoration only.
      expect(bar).toHaveClass('h1', 'hr-skeleton');
      expect(bar).toHaveAttribute('aria-hidden', 'true');
    });

    it('announces nothing itself — the page body skeleton is the one "Loading…"', () => {
      renderHead(<PageHeader loading />);
      expect(screen.queryByRole('status')).toBeNull();
    });

    it('the way back works before the subject arrives', () => {
      renderHead(<PageHeader back={{ to: '/rooms', label: 'Rooms' }} loading />);
      expect(screen.getByRole('link', { name: 'Rooms' })).toHaveAttribute('href', '/rooms');
      expect(screen.queryByRole('heading')).toBeNull();
    });
  });
});

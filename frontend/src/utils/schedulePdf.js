import regularFontUrl from '../assets/fonts/DejaVuSans-latin.ttf?url';
import boldFontUrl from '../assets/fonts/DejaVuSans-Bold-latin.ttf?url';

/**
 * The month as a PDF file on disk.
 *
 * The browser's own print dialog can reach a PDF too, but only by way of a
 * dialog and a destination the reader has to know to change. A rota that is
 * mailed round or filed needs to be a file, so this writes one.
 *
 * Two things here are not obvious. The first is the font: a PDF's built-in
 * Helvetica is encoded for Western Europe and simply has no glyph for c-caron
 * or t-caron, so every second Slovak surname would come out broken or blank.
 * The file therefore carries its own -- DejaVu Sans, cut down to Latin and
 * Latin Extended-A, which is 22 kB rather than the 750 kB the whole face
 * weighs.
 *
 * The second is that the page size is fixed and the type is not: the table is
 * laid out, the pages it produced are counted, and the size is halved in on
 * until the largest one that still stays inside the page budget is found --
 * the same rule the screen follows, reached the same way. The budget is one
 * sheet unless the reader asks for more, because a rota that is read off a
 * wall wants to be one page, and a roster too big for one wants to be legible
 * more than it wants to be single.
 */

/* The printable area, matching what the preview lays out: the page rule's
   margin plus the sheet's own padding, so the file and the screen frame the
   table identically. */
const MARGIN_X_MM = 13;
const MARGIN_Y_MM = 12;

const MIN_FONT_PT = 3;
const MAX_FONT_PT = 11;
const FIT_STEPS = 7;

/* Millimetres of the page kept clear below the last row. Rounding in the
   table's own line breaking can cost a fraction of a row, and a rota whose
   last day fell off the bottom would be worse than a slightly smaller one. */
const BOTTOM_SLACK_MM = 1.5;

const INK = [17, 17, 17];
const RULE = [154, 154, 154];
const HEAD_FILL = [232, 232, 232];
const LABEL_FILL = [244, 244, 244];
const MUTED_FILL = [236, 236, 236];
const MUTED_HEAD_FILL = [224, 224, 224];

const FONT_FAMILY = 'DejaVuSans';

const toBase64 = (buffer) => {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const CHUNK = 0x8000;
  for (let index = 0; index < bytes.length; index += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(index, index + CHUNK));
  }
  return btoa(binary);
};

/* Fetched once per session and kept: the search below builds the document
   several times over, and re-reading the same two files each time would be
   the slowest thing here by far. */
let fontPromise = null;

const loadFonts = () => {
  if (!fontPromise) {
    fontPromise = Promise.all(
      [regularFontUrl, boldFontUrl].map((url) =>
        fetch(url)
          .then((response) => response.arrayBuffer())
          .then(toBase64)
      )
    ).catch((error) => {
      // A failed load must not be remembered as a result.
      fontPromise = null;
      throw error;
    });
  }
  return fontPromise;
};

const registerFonts = (doc, [regular, bold]) => {
  doc.addFileToVFS('DejaVuSans-latin.ttf', regular);
  doc.addFont('DejaVuSans-latin.ttf', FONT_FAMILY, 'normal');
  doc.addFileToVFS('DejaVuSans-Bold-latin.ttf', bold);
  doc.addFont('DejaVuSans-Bold-latin.ttf', FONT_FAMILY, 'bold');
  doc.setFont(FONT_FAMILY, 'normal');
};

/** The two lines of a day heading, "12" over "Ut", as one cell's text. */
const headText = (column) => (column.sub ? `${column.label}\n${column.sub}` : column.label);

const rowText = (row) => (row.sub ? `${row.label} ${row.sub}` : row.label);

/**
 * Draw the workplace and the month above the table, and return the line the
 * table may start on.
 */
const drawHeading = (doc, sheet, pageWidth) => {
  const top = MARGIN_Y_MM + 4;
  doc.setFont(FONT_FAMILY, 'bold');
  doc.setFontSize(11);
  doc.setTextColor(...INK);
  doc.text(sheet.title, MARGIN_X_MM, top);

  doc.setFont(FONT_FAMILY, 'normal');
  doc.setFontSize(9);
  doc.text(sheet.period, pageWidth - MARGIN_X_MM, top, { align: 'right' });

  doc.setDrawColor(51);
  doc.setLineWidth(0.2);
  doc.line(MARGIN_X_MM, top + 1.8, pageWidth - MARGIN_X_MM, top + 1.8);

  return top + 1.8;
};

/** The legend's lines at a given type size, and the height they need. */
const legendLayout = (doc, sheet, fontSizePt, contentWidth) => {
  if (!sheet.legend?.length) return { lines: [], height: 0, lineHeight: 0 };
  doc.setFont(FONT_FAMILY, 'normal');
  doc.setFontSize(fontSizePt);
  const text = sheet.legend.map((item) => `${item.marker}  ${item.label}`).join('     ');
  const lines = doc.splitTextToSize(text, contentWidth);
  const lineHeight = (fontSizePt * 1.2) / 2.835; // pt -> mm
  return { lines, height: lines.length * lineHeight + 1.5, lineHeight };
};

/**
 * Lay the table out at one type size and report what it cost.
 *
 * `minCellHeight` is how the finished sheet spreads a short month down the
 * whole page; the search itself runs without it, because a stretched row says
 * nothing about how much room the content really needs.
 */
const renderTable = async (doc, autoTable, sheet, fontSizePt, options) => {
  const { legendHeight, minCellHeight = 0, pageWidth, pageHeight, startY } = options;

  const contentWidth = pageWidth - 2 * MARGIN_X_MM;
  const firstWidth = contentWidth * sheet.firstColumnShare;
  const otherWidth = (contentWidth - firstWidth) / Math.max(1, sheet.columns.length);

  const columnStyles = {
    0: {
      cellWidth: firstWidth,
      halign: 'left',
      fontStyle: 'bold',
      fillColor: LABEL_FILL,
    },
  };
  sheet.columns.forEach((_column, index) => {
    columnStyles[index + 1] = { cellWidth: otherWidth };
  });

  autoTable(doc, {
    startY,
    margin: {
      top: MARGIN_Y_MM,
      left: MARGIN_X_MM,
      right: MARGIN_X_MM,
      // The legend is not part of the table, so the table is told to stop
      // short of it rather than to run to the bottom of the page.
      bottom: MARGIN_Y_MM + legendHeight + BOTTOM_SLACK_MM,
    },
    theme: 'grid',
    head: [[sheet.firstHead, ...sheet.columns.map(headText)]],
    body: sheet.rows.map((row) => [rowText(row), ...row.cells]),
    styles: {
      font: FONT_FAMILY,
      fontStyle: 'normal',
      fontSize: fontSizePt,
      cellPadding: Math.max(0.3, fontSizePt * 0.1),
      lineColor: RULE,
      lineWidth: 0.1,
      textColor: INK,
      halign: 'center',
      valign: 'middle',
      overflow: 'linebreak',
      minCellHeight,
    },
    headStyles: {
      font: FONT_FAMILY,
      fontStyle: 'bold',
      fillColor: HEAD_FILL,
      textColor: INK,
      halign: 'center',
      valign: 'middle',
      minCellHeight: 0,
    },
    columnStyles,
    didParseCell: (data) => {
      const column = sheet.columns[data.column.index - 1];
      if (data.section === 'head') {
        if (column?.muted) data.cell.styles.fillColor = MUTED_HEAD_FILL;
        return;
      }
      const row = sheet.rows[data.row.index];
      if (row?.muted) {
        data.cell.styles.fillColor =
          data.column.index === 0 ? MUTED_HEAD_FILL : MUTED_FILL;
      } else if (column?.muted && data.column.index > 0) {
        data.cell.styles.fillColor = MUTED_FILL;
      }
    },
  });

  const drawn = doc.lastAutoTable;
  const finalY = drawn.finalY;
  return {
    finalY,
    pages: doc.getNumberOfPages(),
    /* Where the body starts, so a later pass can work out how much taller its
       rows would have to be to reach the foot of the page. */
    bodyTop: (drawn.settings?.startY ?? startY) + (drawn.head?.[0]?.height ?? 0),
    fits:
      doc.getNumberOfPages() <= options.maxPages &&
      finalY + legendHeight + BOTTOM_SLACK_MM <= pageHeight - MARGIN_Y_MM,
  };
};

const drawLegend = (doc, legend, startY, lineHeight) => {
  if (!legend.lines.length) return;
  doc.setFont(FONT_FAMILY, 'normal');
  doc.setTextColor(...INK);
  legend.lines.forEach((line, index) => {
    doc.text(line, MARGIN_X_MM, startY + 3 + index * lineHeight);
  });
};

/**
 * Build the sheet as a PDF document, without saving it.
 *
 * `sheet` is the print screen's own table model: { title, period, firstHead,
 * columns: [{label, sub, muted}], rows: [{label, sub, muted, cells}],
 * legend: [{marker, label}], firstColumnShare }.
 *
 * `maxPages` is how many sheets the reader is willing to spend; the type is
 * made as large as that many pages allow.
 */
export async function buildSchedulePdf(sheet, orientation = 'portrait', maxPages = 1) {
  const [{ jsPDF }, { default: autoTable }, fonts] = await Promise.all([
    import('jspdf'),
    import('jspdf-autotable'),
    loadFonts(),
  ]);

  const pageBudget = Math.max(1, Math.round(maxPages) || 1);

  const build = async (fontSizePt, minCellHeight) => {
    const doc = new jsPDF({ orientation, unit: 'mm', format: 'a4' });
    registerFonts(doc, fonts);
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const startY = drawHeading(doc, sheet, pageWidth) + 2;
    const legend = legendLayout(doc, sheet, fontSizePt, pageWidth - 2 * MARGIN_X_MM);
    const result = await renderTable(doc, autoTable, sheet, fontSizePt, {
      legendHeight: legend.height,
      maxPages: pageBudget,
      minCellHeight,
      pageWidth,
      pageHeight,
      startY,
    });
    return { doc, legend, pageHeight, ...result };
  };

  let low = MIN_FONT_PT;
  let high = MAX_FONT_PT;
  let best = null;
  let bestSize = MIN_FONT_PT;
  for (let step = 0; step < FIT_STEPS; step += 1) {
    const mid = (low + high) / 2;
    // Each size is laid out from the previous one's verdict; there is nothing
    // here to run in parallel.
    const attempt = await build(mid, 0);
    if (attempt.fits) {
      best = attempt;
      bestSize = mid;
      low = mid;
    } else {
      high = mid;
    }
  }

  if (!best) best = await build(MIN_FONT_PT, 0);

  /* A month of few rows would otherwise sit in the top half of the page. Give
     every row the share of the page that is actually left: the foot of the
     table should land just above the legend, so the height to divide is the
     run from where the body starts down to there.

     If stretching costs a page after all -- rounding, or a row that grows a
     line rather than a millimetre -- the unstretched sheet stands. One page is
     the promise; filling it is only a courtesy. */
  /* Only a sheet that came out on one page is stretched. Spread over several,
     the last page holds whatever the ones before it left, and stretching its
     handful of rows over a whole sheet would say the month ends in rows three
     centimetres tall. */
  const rowCount = best.pages === 1 ? sheet.rows.length : 0;
  const footLine = best.pageHeight - MARGIN_Y_MM - BOTTOM_SLACK_MM - best.legend.height;
  if (rowCount > 0 && footLine - best.finalY > 1) {
    const stretched = await build(bestSize, (footLine - best.bodyTop) / rowCount);
    if (stretched.fits) best = stretched;
  }

  drawLegend(best.doc, best.legend, best.finalY, best.legend.lineHeight);
  return best.doc;
}

/** Build the sheet and hand it to the browser as a downloaded file. */
export async function downloadSchedulePdf(
  filename,
  sheet,
  orientation = 'portrait',
  maxPages = 1
) {
  const doc = await buildSchedulePdf(sheet, orientation, maxPages);
  doc.save(filename);
}

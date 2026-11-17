# PDF CJK font

The portable build downloads `SourceHanSansSC-Regular.otf` from the official
Adobe Source Han Sans release branch during CI. The font is not stored in Git,
which keeps the source repository and release workflow payload small.

Source: https://github.com/adobe-fonts/source-han-sans

License: SIL Open Font License 1.1, copied in `LICENSE-SourceHanSans.txt`.

At runtime the PDF renderer prefers `REFRACDRAFT_CJK_FONT`, then the Windows
system CJK fonts, then this bundled font, then common system fallbacks.

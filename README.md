Set files of `x9u-in-1105-sultra` (ColorOS 17, Find X9 Ultra IN, November image),
each named by its SHA-256, the name the OneOS app downloads it under. Files larger
than GitHub's per-file limit are stored as `<sha256>.part-NN` and joined in order.

The owner publishes them as the release named after this branch (the part after
`set-files/`) by running the "Publish set files" workflow by hand; the workflow
joins the parts and checks every file against the hash pinned in
`app-android/packages/x9u-in-1105-sultra.sha256` before anything is published.

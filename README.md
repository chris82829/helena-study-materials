HELENA research materials


participants/: 347 participants, each with one subfolder and one TXT file per question.
condition/answer.txt contains A, B or C. MISSING represents an empty cell
(for rating items: "cannot judge", see questionnaire/scale.txt).
There are 20 rating questions, two prior-experience questions and free-text feedback.
The 80 free-text comments were reviewed, and locations and other potentially
identifying details were generalized.


questionnaire/: For each question, the German wording as administered to participants,
the English translation reported in the paper, the source item in ResQue or CRS-Que,
and the documented adaptation. questionnaire/scale.txt describes the answer scale
and the coding of missing values.


analysis/: Versioned quantitative reproduction script. Install its requirements and run
`python analysis/analyze.py --output /tmp/helena-statistics.json`. It reads the
individual TXT responses, records input and script SHA-256 hashes, and uses
5,000 deterministic bootstrap resamples. This publication adaptation does not
establish historical use or a pre-study freeze. Dropout records and qualitative
category assignments are not included in the public responses.

system/: HELENA source code with questionnaire wording from the supplied correction
files, a seven-point rating scale, and a shared base prompt for B and C. C appends
the configured persona. This is a publication adaptation, not a certified snapshot
of the historical deployment. No runtime databases, job corpus, CVs, chat histories,
API keys or other credentials are included. Copy system/.env.example to system/.env,
provide your own API key, job database and model cache, configure the privacy
settings for your deployment, then run `docker compose up --build` in system/.
The bundled privacy configuration intentionally remains unapproved.

export default {
  branches: ['master'],
  tagFormat: 'v${version}',
  plugins: [
    '@semantic-release/commit-analyzer',
    '@semantic-release/release-notes-generator',
    [
      '@semantic-release/exec',
      {
        prepareCmd:
          'uv version ${nextRelease.version} --no-sync && npm --prefix frontend version ${nextRelease.version} --no-git-tag-version',
        successCmd:
          'echo "new_release_published=true" >> "$GITHUB_OUTPUT" && echo "new_release_version=${nextRelease.version}" >> "$GITHUB_OUTPUT"',
      },
    ],
    [
      '@semantic-release/git',
      {
        assets: [
          'pyproject.toml',
          'uv.lock',
          'frontend/package.json',
          'frontend/package-lock.json',
        ],
        message: 'chore(release): ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}',
      },
    ],
    '@semantic-release/github',
  ],
};

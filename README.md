### Lumir Sliva

Senior Storage Engineer at [Seznam.cz](https://www.seznam.cz), Prague.
I do stuff in the cloud. ☁️

Upstream contributor to [Ceph](https://github.com/ceph/ceph/pulls?q=is%3Apr+author%3Alumir-sliva) and [Rook](https://github.com/rook/rook/pulls?q=is%3Apr+author%3Alumir-sliva).

#### Selected contributions

**Ceph**
- rgw/lc: report `x-amz-expiration` only for the current version ([#69642](https://github.com/ceph/ceph/pull/69642), backported to squid & tentacle)
- rgw: add `Retry-After` header and configurable rate-limit response ([#68210](https://github.com/ceph/ceph/pull/68210))
- rgw: avoid doubled ARN in GetBucketReplication for pre-existing data ([#68137](https://github.com/ceph/ceph/pull/68137))
- rgw: account presigned POST bytes_received in usage log ([#68571](https://github.com/ceph/ceph/pull/68571))
- mon: surface data dir + db size as perf counters ([#68916](https://github.com/ceph/ceph/pull/68916))
- mon: show CRUSH rule name in `osd pool ls detail` ([#68886](https://github.com/ceph/ceph/pull/68886))
- osd/OSDMap: don't abort on float rounding in read balancer ([#71772](https://github.com/ceph/ceph/pull/71772))
- mgr/cephadm: don't treat unknown daemon state as error ([#68290](https://github.com/ceph/ceph/pull/68290))
- crimson/os/seastore: handle ENOENT in `SeaStore::Shard::stat` ([#68333](https://github.com/ceph/ceph/pull/68333))

**Rook**
- mon: relax balanced CRUSH weight check for stretch mode ([#17288](https://github.com/rook/rook/pull/17288))
- doc: add CSI operator resource cleanup steps to teardown guide ([#17286](https://github.com/rook/rook/pull/17286))

[All merged pull requests](https://github.com/search?q=author%3Alumir-sliva+is%3Apr+is%3Amerged&type=pullrequests)

#### Projects
- [ceph-ansimple](https://github.com/lumir-sliva/ceph-ansimple): simplified Ceph deployment with Ansible

Off the clock: flight-sim and game tooling ([briefing-room-for-dcs](https://github.com/DCS-BR-Tools/briefing-room-for-dcs), [WARDOGS calculator](https://github.com/apollyon-sys/wardogs-calculator)).

#### Stats

<p>
  <img height="165" src="https://github-stats-extended.vercel.app/api?username=lumir-sliva&show_icons=true&include_all_commits=true&show=prs_merged&theme=transparent&hide_border=true" alt="GitHub stats" />
  <img height="165" src="https://streak-stats.demolab.com?user=lumir-sliva&theme=transparent&hide_border=true" alt="Contribution streak" />
</p>

package main

// Spike #11: a "moby" exporter for stock BuildKit, so buildx's docker driver
// (which always asks for exporter "moby" on --load / -t) works against a
// buildkitd that is not dockerd. It runs the stock image exporter, writes an
// OCI archive of the result into a host-shared drop dir, and blocks until the
// host side has loaded it into Apple's image store.

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	archiveexporter "github.com/containerd/containerd/v2/core/images/archive"
	"github.com/moby/buildkit/cache"
	cacheconfig "github.com/moby/buildkit/cache/config"
	"github.com/moby/buildkit/client"
	"github.com/moby/buildkit/exporter"
	"github.com/moby/buildkit/exporter/containerimage/exptypes"
	"github.com/moby/buildkit/session"
	"github.com/moby/buildkit/util/contentutil"
	"github.com/moby/buildkit/util/progress"
	"github.com/moby/buildkit/worker/base"
	ocispecs "github.com/opencontainers/image-spec/specs-go/v1"
	"github.com/pkg/errors"
)

type mobyWorker struct{ *base.Worker }

func (w *mobyWorker) Exporter(name string, sm *session.Manager) (exporter.Exporter, error) {
	if name != "moby" {
		return w.Worker.Exporter(name, sm)
	}
	inner, err := w.Worker.Exporter(client.ExporterImage, sm)
	if err != nil {
		return nil, err
	}
	return &mobyExporter{inner: inner, w: w.Worker}, nil
}

type mobyExporter struct {
	inner exporter.Exporter
	w     *base.Worker
}

func (e *mobyExporter) Resolve(ctx context.Context, id int, attrs map[string]string) (exporter.ExporterInstance, error) {
	a := make(map[string]string, len(attrs))
	for k, v := range attrs {
		a[k] = v
	}
	inst, err := e.inner.Resolve(ctx, id, a)
	if err != nil {
		return nil, err
	}
	return &mobyInstance{ExporterInstance: inst, w: e.w, attrs: attrs}, nil
}

type mobyInstance struct {
	exporter.ExporterInstance
	w     *base.Worker
	attrs map[string]string
}

func (i *mobyInstance) Export(ctx context.Context, src *exporter.Source, bi exporter.ExportBuildInfo) (map[string]string, exporter.FinalizeFunc, exporter.DescriptorReference, error) {
	resp, fin, ref, err := i.ExporterInstance.Export(ctx, src, bi)
	if err != nil {
		return resp, fin, ref, err
	}

	var desc ocispecs.Descriptor
	if s, ok := resp[exptypes.ExporterImageDescriptorKey]; ok {
		dt, err := base64.StdEncoding.DecodeString(s)
		if err != nil {
			return nil, nil, nil, err
		}
		if err := json.Unmarshal(dt, &desc); err != nil {
			return nil, nil, nil, err
		}
	} else if ref != nil {
		desc = ref.Descriptor()
	} else {
		return nil, nil, nil, errors.New("moby: no image descriptor")
	}
	// The descriptor may carry buildkit-internal annotations; keep it plain.
	desc.Annotations = nil

	var names []string
	raw := resp[exptypes.ExporterImageNameKey]
	if raw == "" {
		raw = i.attrs["name"]
	}
	for _, n := range strings.Split(raw, ",") {
		if n = strings.TrimSpace(n); n != "" {
			names = append(names, n)
		}
	}

	mprovider := contentutil.NewMultiProvider(i.w.ContentStore())
	refs := []cache.ImmutableRef{}
	if src.Ref != nil {
		refs = append(refs, src.Ref)
	}
	for _, r := range src.Refs {
		if r != nil {
			refs = append(refs, r)
		}
	}
	refCfg := cacheconfig.RefConfig{Compression: i.Config().Compression()}
	for _, r := range refs {
		remotes, err := r.GetRemotes(ctx, false, refCfg, false, session.NewGroup(bi.SessionID))
		if err != nil {
			return nil, nil, nil, err
		}
		if len(remotes) == 0 {
			continue
		}
		rm := remotes[0]
		if u, ok := rm.Provider.(cache.Unlazier); ok {
			if err := u.Unlazy(ctx); err != nil {
				return nil, nil, nil, err
			}
		}
		for _, d := range rm.Descriptors {
			mprovider.Add(d.Digest, rm.Provider)
		}
	}

	report := progress.OneOff(ctx, "fruitlocker: loading into Apple image store")
	if err := handoff(ctx, mprovider, desc, names); err != nil {
		return nil, nil, nil, report(err)
	}
	report(nil)
	return resp, fin, ref, nil
}

func handoff(ctx context.Context, p *contentutil.MultiProvider, desc ocispecs.Descriptor, names []string) error {
	dir := os.Getenv("FL_EXPORT_DIR")
	if dir == "" {
		dir = "/fl-export"
	}
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	id := hex.EncodeToString(b)
	tmp := filepath.Join(dir, id+".partial")
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	opts := []archiveexporter.ExportOpt{
		archiveexporter.WithManifest(desc, names...),
		archiveexporter.WithAllPlatforms(),
		archiveexporter.WithSkipDockerManifest(),
	}
	if err := archiveexporter.Export(ctx, p, f, opts...); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, filepath.Join(dir, id+".tar")); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, id+".ready"), []byte(strings.Join(names, "\n")), 0o644); err != nil {
		return err
	}
	deadline := time.Now().Add(10 * time.Minute)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(filepath.Join(dir, id+".done")); err == nil {
			return nil
		}
		if dt, err := os.ReadFile(filepath.Join(dir, id+".err")); err == nil {
			return errors.Errorf("fruitlocker load failed: %s", strings.TrimSpace(string(dt)))
		}
		select {
		case <-ctx.Done():
			return context.Cause(ctx)
		case <-time.After(100 * time.Millisecond):
		}
	}
	return errors.New("fruitlocker load timed out")
}

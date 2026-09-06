importScripts ('occt-import-js.js');

onmessage = async function (ev)
{
	let modulOverrides = {
		locateFile: function (path) {
			return path;
		}
	};
	let occt = await occtimportjs (modulOverrides);
	let fn = { step: 'ReadStepFile', iges: 'ReadIgesFile', brep: 'ReadBrepFile' }[ev.data.format] || 'ReadStepFile';
	let result = occt[fn] (ev.data.buffer, ev.data.params);
	postMessage (result);
};

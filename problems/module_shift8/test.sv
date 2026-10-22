`timescale 1 ps/1 ps
`define OK 12
`define INCORRECT 13


module stimulus_gen (
	input clk,
	output logic [7:0] d,
	output logic [1:0] sel
);

	initial begin
		@(posedge clk) begin d <= 8'd18; sel <= 2'd0; end
		@(posedge clk) begin d <= 8'd52; sel <= 2'd1; end
		@(posedge clk) begin d <= 8'd86; sel <= 2'd2; end
		@(posedge clk) begin d <= 8'd120; sel <= 2'd3; end
		@(posedge clk) begin d <= 8'd154; sel <= 2'd0; end
		@(posedge clk) begin d <= 8'd188; sel <= 2'd1; end
		@(posedge clk) begin d <= 8'd222; sel <= 2'd2; end
		@(posedge clk) begin d <= 8'd240; sel <= 2'd3; end
		@(posedge clk) begin d <= 8'd19; sel <= 2'd1; end
		@(posedge clk) begin d <= 8'd87; sel <= 2'd2; end
		repeat(300) @(posedge clk, negedge clk) begin d <= $random; sel <= $random; end
		#1 $finish;
	end

endmodule

module tb();

	typedef struct packed {
		int errors;
		int errortime;
		int errors_q;
		int errortime_q;

		int clocks;
	} stats;

	stats stats1;

	reg clk=0;
	initial forever
		#5 clk = ~clk;

	logic [7:0] d;
	logic [1:0] sel;
	logic [7:0] q_ref;
	logic [7:0] q_dut;

	initial begin
		$dumpfile("wave.vcd");
		$dumpvars(1, stim1.clk, tb_mismatch, clk, d, sel, q_ref, q_dut);
	end

	wire tb_match;
	wire tb_mismatch = ~tb_match;

	stimulus_gen stim1 (.clk, .d, .sel);
	RefModule good1 (.clk, .d, .sel, .q(q_ref));
	TopModule top_module1 (.clk, .d, .sel, .q(q_dut));

	final begin
		if (stats1.errors_q) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "q", stats1.errors_q, stats1.errortime_q);
		else $display("Hint: Output '%s' has no mismatches.", "q");
		$display("Hint: Total mismatched samples is %1d out of %1d samples\n", stats1.errors, stats1.clocks);
		$display("Simulation finished at %0d ps", $time);
		$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
	end

	assign tb_match = ( { q_ref } === ( { q_ref } ^ { q_dut } ^ { q_ref } ) );

	always @(posedge clk, negedge clk) begin
		stats1.clocks++;
		if (!tb_match) begin
			if (stats1.errors == 0) stats1.errortime = $time;
			stats1.errors++;
		end
		if (q_ref !== ( q_ref ^ q_dut ^ q_ref ))
		begin if (stats1.errors_q == 0) stats1.errortime_q = $time;
			stats1.errors_q = stats1.errors_q+1'b1; end
	end

	initial begin
		#1000000
		$display("TIMEOUT");
		$finish();
	end

endmodule
